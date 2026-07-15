from django.db.models import Sum
from django.db.models.functions import TruncMonth, TruncDate
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.http import JsonResponse
from django.utils import timezone
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt
from datetime import timedelta

from .models import UserProfile, HydrationLog, Friendship, UserAchievement, Nudge, HydrationGroup, GroupChallenge
import json
import urllib.request


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

    unread_nudges = Nudge.objects.filter(receiver=request.user, is_read=False).select_related('sender')

    context = {
        'profile': profile,
        'current_intake': round(profile.current_intake, 2),
        'leaderboard': leaderboard,
        'history_logs': json.dumps(history_logs),
        'unread_nudges': unread_nudges,  # 🌟 PASS UNREAD NUDGES TO HTML
    }
    return render(request, 'tracker/index.html', context)


@csrf_exempt
@login_required
def log_water_api(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            amount = float(data.get('amount', 0.25))
            bev_type = data.get('beverage_type', 'water')
        except Exception:
            amount = 0.25
            bev_type = 'water'

        profile = request.user.profile

        # 🌟 Create Hydration Log (the model save() method automatically calculates net_amount)
        log = HydrationLog.objects.create(
            user=request.user,
            amount=amount,
            beverage_type=bev_type
        )

        # 🌟 Update user's daily progress using the calculated net hydration amount
        profile.current_intake = round(float(profile.current_intake) + log.net_hydration, 2)
        profile.save()

        # 🌟 Increment active Group Challenges for any groups this user is in
        active_challenges = GroupChallenge.objects.filter(
            group__members=request.user,
            is_active=True,
            end_date__gte=timezone.localdate()
        )
        for challenge in active_challenges:
            challenge.current_volume = round(challenge.current_volume + log.net_amount, 2)
            challenge.save()

        # Check streak achievements on logging
        today = timezone.localdate()
        if profile.current_intake >= profile.daily_goal and profile.last_streak_date != today:
            profile.streak += 1
            profile.last_streak_date = today
            profile.save()

            # Check achievements on successful hydration log
            profile.check_and_award_achievements()

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

    # Fetch earned achievements to render on screen
    earned = UserAchievement.objects.filter(user=request.user).select_related('achievement')
    context = {
        'profile': profile,
        'earned_achievements': earned
    }
    return render(request, 'tracker/profile.html', context)


@login_required
def sync_weather_api(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            lat = float(data.get('latitude'))
            lon = float(data.get('longitude'))

            profile = request.user.profile
            profile.latitude = lat
            profile.longitude = lon

            # Fetch current temperature from Open-Meteo's free public API
            url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m"
            req = urllib.request.Request(url, headers={'User-Agent': 'HydrateCorePro/1.0'})

            with urllib.request.urlopen(req) as response:
                weather_data = json.loads(response.read().decode())
                current_temp = weather_data['current']['temperature_2m']

            # Smart Climate Factor Calculation:
            # Under 20°C: temperate (0.0L)
            # 20°C - 30°C: warm (0.25L)
            # Over 30°C: hot/humid (0.50L adjustment)
            if current_temp > 30.0:
                profile.climate_factor = 0.50
            elif current_temp > 20.0:
                profile.climate_factor = 0.25
            else:
                profile.climate_factor = 0.0

            profile.update_daily_goal()

            return JsonResponse({
                'status': 'success',
                'temperature': current_temp,
                'climate_factor': profile.climate_factor,
                'daily_goal': profile.daily_goal
            })
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    return JsonResponse({'status': 'invalid method'}, status=400)

@csrf_exempt
@login_required
def send_nudge_api(request, username):
    """Creates a new unread nudge for a friend"""
    if request.method == 'POST':
        try:
            receiver = User.objects.get(username=username)
            # Ensure they are friends before allowing a nudge
            is_friend = Friendship.objects.filter(from_user=request.user, to_user=receiver).exists()
            if not is_friend:
                return JsonResponse({'status': 'error', 'message': 'Not friends'}, status=400)

            # Create the nudge record
            Nudge.objects.create(sender=request.user, receiver=receiver)
            return JsonResponse({'status': 'success'})
        except User.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'User not found'}, status=404)
    return JsonResponse({'status': 'invalid method'}, status=400)
pass


@csrf_exempt
@login_required
def dismiss_nudges_api(request):
    """Marks all pending nudges for the logged-in user as read"""
    if request.method in ['POST', 'GET']:
        if not request.user.is_authenticated:
            return JsonResponse({'status': 'error', 'message': 'User session expired. Please log in again.'},
                                status=401)

        # Mark all pending nudges for this user as read
        updated_count = Nudge.objects.filter(receiver=request.user, is_read=False).update(is_read=True)
        return JsonResponse({
            'status': 'success',
            'message': f'Successfully dismissed {updated_count} nudges.'
        })
    return JsonResponse({'status': 'invalid method'}, status=400)


@login_required
def analytics_data_api(request, range_type):
    """Returns aggregated hydration data for charts based on range selection"""
    today = timezone.localdate()

    if range_type == 'weekly':
        # Last 7 days
        start_date = today - timedelta(days=6)
        logs = HydrationLog.objects.filter(
            user=request.user,
            timestamp__date__range=[start_date, today]
        ).annotate(date=TruncDate('timestamp')) \
            .values('date') \
            .annotate(total_raw=Sum('amount'), total_net=Sum('net_hydration')) \
            .order_by('date')

        # Ensure every day in the range has a data point (fill missing with 0)
        raw_map = {start_date + timedelta(days=i): 0.0 for i in range(7)}
        net_map = {start_date + timedelta(days=i): 0.0 for i in range(7)}

    elif range_type == 'monthly':
        # Last 30 days
        start_date = today - timedelta(days=29)
        logs = HydrationLog.objects.filter(
            user=request.user,
            timestamp__date__range=[start_date, today]
        ).annotate(date=TruncDate('timestamp')) \
            .values('date') \
            .annotate(total_raw=Sum('amount'), total_net=Sum('net_hydration')) \
            .order_by('date')

        raw_map = {start_date + timedelta(days=i): 0.0 for i in range(30)}
        net_map = {start_date + timedelta(days=i): 0.0 for i in range(30)}

    elif range_type == 'yearly':
        # Last 12 months
        start_date = today - timedelta(days=365)
        logs = HydrationLog.objects.filter(
            user=request.user,
            timestamp__date__range=[start_date, today]
        ).annotate(month=TruncMonth('timestamp')) \
            .values('month') \
            .annotate(total_raw=Sum('amount'), total_net=Sum('net_hydration')) \
            .order_by('month')

        labels = []
        raw_data = []
        net_data = []

        # Maps to group raw and net sums by month string
        raw_month_map = {}
        net_month_map = {}
        for log in logs:
            month_str = log['month'].strftime('%b %Y')
            raw_month_map[month_str] = round(log['total_raw'] or 0.0, 2)
            net_month_map[month_str] = round(log['total_net'] or 0.0, 2)

        for i in range(12):
            m_date = today - timedelta(days=30 * (11 - i))
            m_str = m_date.strftime('%b %Y')
            labels.append(m_str)
            raw_data.append(raw_month_map.get(m_str, 0.0))
            net_data.append(net_month_map.get(m_str, 0.0))

        return JsonResponse({
            'labels': labels,
            'raw_data': raw_data,
            'net_data': net_data
        })

    else:
        return JsonResponse({'status': 'error', 'message': 'Invalid range'}, status=400)

    # 🌟 Populate weekly/monthly dual-data maps using correct aggregation keys
    for log in logs:
        log_date = log['date']
        if log_date in raw_map:
            raw_map[log_date] = round(log['total_raw'] or 0.0, 2)
            net_map[log_date] = round(log['total_net'] or 0.0, 2)

    labels = [date.strftime('%a (%d)' if range_type == 'weekly' else '%d %b') for date in raw_map.keys()]

    return JsonResponse({
        'labels': labels,
        'raw_data': list(raw_map.values()),
        'net_data': list(net_map.values())
    })


@login_required
def check_new_nudges_api(request):
    """API for the Service Worker to fetch unread nudges and trigger background notifications"""
    if request.method in ['GET', 'POST']:
        # Fetch unread nudges
        unread_nudges = Nudge.objects.filter(receiver=request.user, is_read=False).select_related('sender')

        nudge_list = []
        for nudge in unread_nudges:
            nudge_list.append({
                'id': nudge.id,
                'sender': nudge.sender.username,
            })

        return JsonResponse({
            'status': 'success',
            'unread_count': len(nudge_list),
            'nudges': nudge_list
        })
    return JsonResponse({'status': 'invalid method'}, status=400)


@login_required
def use_rescue_api(request):
    """Uses a Streak Rescue token to protect a broken hydration streak"""
    if request.method == 'POST':
        profile = request.user.profile
        if profile.streak_rescues > 0:
            profile.streak_rescues -= 1
            # Prevent resetting by setting streak date to today
            profile.last_streak_date = timezone.localdate()
            # If streak is 0, give them an instant +1 rescue boost
            if profile.streak == 0:
                profile.streak = 1
            profile.save()
            return JsonResponse({'status': 'success', 'rescues': profile.streak_rescues, 'streak': profile.streak})
        return JsonResponse({'status': 'error', 'message': 'No rescues left!'}, status=400)


@login_required
def join_group_api(request):
    """Lets users join or create a shared social hydration group"""
    if request.method == 'POST':
        data = json.loads(request.body)
        group_name = data.get('group_name', '').strip()
        if not group_name:
            return JsonResponse({'status': 'error', 'message': 'Group name cannot be empty'}, status=400)

        group, created = HydrationGroup.objects.get_or_create(name=group_name)
        group.members.add(request.user)

        # Create a default Group Challenge if it is a brand-new group
        if created:
            GroupChallenge.objects.create(
                group=group,
                title=f"First Team Goal: {group_name}",
                target_volume=50.0,
                end_date=timezone.localdate() + timedelta(days=7)
            )

        return JsonResponse({'status': 'success', 'group_name': group.name})


# 🌟 UPDATE: Advanced Double Dataset Analytics API
@login_required
def analytics_data_api(request, range_type):
    today = timezone.localdate()
    start_date = today - timedelta(days=6) if range_type == 'weekly' else today - timedelta(days=29)

    logs = HydrationLog.objects.filter(
        user=request.user,
        timestamp__date__range=[start_date, today]
    ).annotate(date=TruncDate('timestamp')) \
        .values('date') \
        .annotate(total_raw=Sum('amount'), total_net=Sum('net_amount')) \
        .order_by('date')

    # Fill missing days
    days_to_track = 7 if range_type == 'weekly' else 30
    raw_map = {start_date + timedelta(days=i): 0.0 for i in range(days_to_track)}
    net_map = {start_date + timedelta(days=i): 0.0 for i in range(days_to_track)}

    for log in logs:
        log_date = log['date']
        if log_date in raw_map:
            raw_map[log_date] = round(log['total_raw'], 2)
            net_map[log_date] = round(log['total_net'], 2)

    labels = [date.strftime('%a (%d)' if range_type == 'weekly' else '%d %b') for date in raw_map.keys()]

    return JsonResponse({
        'labels': labels,
        'raw_data': list(raw_map.values()),  # Total fluids drunk
        'net_data': list(net_map.values())  # True cellular water hydration
    })