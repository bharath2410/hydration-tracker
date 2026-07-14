from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.http import JsonResponse
from django.utils import timezone
from django.contrib.auth.models import User
from .models import UserProfile, HydrationLog, Friendship
import json


def register(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            UserProfile.objects.create(user=user)
            login(request, user)
            return redirect('index')
    else:
        form = UserCreationForm()
    return render(request, 'registration/register.html', {'form': form})


@login_required
def index(request):
    profile, created = UserProfile.objects.get_or_create(user=request.user)

    # Process Metabolic Fluid Degradation (Feature 3)
    # Deducts water at a rate of 0.1L per hour automatically upon app access
    now = timezone.now()
    time_passed = now - profile.last_decay_time
    hours_passed = time_passed.total_seconds() / 3600.0

    if hours_passed >= 1.0:
        decay_amount = int(hours_passed) * 0.1
        HydrationLog.objects.create(user=request.user, amount=-decay_amount, timestamp=now)
        profile.last_decay_time = now
        profile.save()

    # Dynamic Streak Maintenance Checks
    today = timezone.localdate()
    yesterday = today - timezone.timedelta(days=1)

    # Calculate yesterday's total
    yesterday_logs = HydrationLog.objects.filter(user=request.user, timestamp__date=yesterday)
    yesterday_total = sum(log.amount for log in yesterday_logs)

    if profile.last_streak_date and profile.last_streak_date < yesterday and yesterday_total < profile.daily_goal:
        profile.streak = 0
        profile.save()

    # Build Friend Social Leaderboard Dataset (Feature 1)
    friend_ids = Friendship.objects.filter(from_user=request.user).values_list('to_user_id', flat=True)
    friends = User.objects.filter(id__in=friend_ids)

    leaderboard = []
    # Include current user in standings
    current_ratio = min((profile.current_intake / profile.daily_goal) * 100, 100) if profile.daily_goal else 0
    leaderboard.append({
        'username': 'You',
        'intake': round(profile.current_intake, 2),
        'goal': round(profile.daily_goal, 2),
        'ratio': round(current_ratio, 1),
        'streak': profile.streak
    })

    for friend in friends:
        f_profile = friend.profile
        f_ratio = min((f_profile.current_intake / f_profile.daily_goal) * 100, 100) if f_profile.daily_goal else 0
        leaderboard.append({
            'username': friend.username,
            'intake': round(f_profile.current_intake, 2),
            'goal': round(f_profile.daily_goal, 2),
            'ratio': round(f_ratio, 1),
            'streak': f_profile.streak
        })
    # Sort leaderboard by highest completion percentage
    leaderboard = sorted(leaderboard, key=lambda x: x['ratio'], reverse=True)

    # 7-Day Performance Metric Graph Generation
    history_logs = []
    for i in range(6, -1, -1):
        day = today - timezone.timedelta(days=i)
        day_logs = HydrationLog.objects.filter(user=request.user, timestamp__date=day)
        history_logs.append(round(max(0.0, sum(log.amount for log in day_logs)), 2))

    context = {
        'profile': profile,
        'current_intake': round(profile.current_intake, 2),
        'leaderboard': leaderboard,
        'history_logs': json.dumps(history_logs),
    }
    return render(request, 'tracker/index.html', context)


@login_required
def log_water_api(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            amount = float(data.get('amount', 0.25))
            bev_type = data.get('beverage_type', 'water')
        except:
            amount = 0.25
            bev_type = 'water'

        # 🌟 Define hydration multipliers
        modifiers = {
            'water': 1.0,
            'sports': 1.2,
            'caffeine': 0.8,
            'alcohol': -0.5
        }
        mod = modifiers.get(bev_type, 1.0)

        profile = request.user.profile

        # Create log with type and modifier parameters
        HydrationLog.objects.create(
            user=request.user,
            amount=amount,
            beverage_type=bev_type,
            modifier=mod
        )

        # Check streak achievements on logging
        today = timezone.localdate()
        if profile.current_intake >= profile.daily_goal and profile.last_streak_date != today:
            profile.streak += 1
            profile.last_streak_date = today
            profile.save()

        return JsonResponse({
            'status': 'success',
            'current_intake': round(profile.current_intake, 2),
            'streak': profile.streak
        })
    return JsonResponse({'status': 'invalid method'}, status=400)


@login_required
def update_profile_api(request):
    """Fallback REST API for quick adjustments"""
    if request.method == 'POST':
        data = json.loads(request.body)
        profile = request.user.profile
        profile.weight = float(data.get('weight', profile.weight))
        profile.activity_level = float(data.get('activity', profile.activity_level))
        profile.climate_factor = float(data.get('climate', profile.climate_factor))

        # 🌟 UPDATED: Matches the clean direct Liters format used elsewhere
        custom_vol = float(data.get('custom_ml', 0.40))
        if custom_vol > 10:  # Simple safety fallback: if they send 400 instead of 0.40, convert it
            custom_vol = custom_vol / 1000.0
        profile.custom_volume = custom_vol

        profile.update_daily_goal()
        return JsonResponse({'status': 'success', 'daily_goal': profile.daily_goal})
    return JsonResponse({'status': 'invalid method'}, status=400)


@login_required
def add_friend(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        try:
            target_user = User.objects.get(username=username)
            if target_user != request.user:
                Friendship.objects.get_or_create(from_user=request.user, to_user=target_user)
                Friendship.objects.get_or_create(from_user=target_user, to_user=request.user)  # Mutual link
        except User.DoesNotExist:
            pass
    return redirect('index')


@login_required
def profile_view(request):
    profile = request.user.profile

    if request.method == "POST":
        try:
            # 🌟 UPDATED: Read from request.POST instead of json.loads
            profile.weight = float(request.POST.get('weight', profile.weight))
            profile.height = float(request.POST.get('height', profile.height))
            profile.age = int(request.POST.get('age', profile.age))
            profile.gender = request.POST.get('gender', profile.gender)
            profile.activity_level = float(request.POST.get('activity', profile.activity_level))
            profile.climate_factor = float(request.POST.get('climate', profile.climate_factor))
            profile.custom_volume = float(request.POST.get('custom_ml', profile.custom_volume))
            profile.theme_preference = request.POST.get('theme', profile.theme_preference)
            # Handle custom manual goal override
            override_val = request.POST.get('custom_goal_override')
            if override_val and str(override_val).strip():
                profile.custom_goal_override = float(override_val)
            else:
                profile.custom_goal_override = None

            # 🌟 NEW: Save uploaded image from request.FILES
            if 'profile_picture' in request.FILES:
                profile.profile_picture = request.FILES['profile_picture']

            profile.update_daily_goal()
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    return render(request, 'tracker/profile.html', {'profile': profile})