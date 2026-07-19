import traceback
import json
import urllib.request
from datetime import timedelta

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

from .models import UserProfile, HydrationLog, Friendship, UserAchievement, Nudge, HydrationGroup, GroupChallenge


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

    # Process Metabolic Fluid Degradation
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

    yesterday_logs = HydrationLog.objects.filter(user=request.user, timestamp__date=yesterday)
    yesterday_total = sum(log.amount for log in yesterday_logs)

    if profile.last_streak_date and profile.last_streak_date < yesterday and yesterday_total < profile.daily_goal:
        profile.streak = 0
        profile.save()

    # Build Friend Social Leaderboard Dataset
    friend_ids = Friendship.objects.filter(from_user=request.user).values_list('to_user_id', flat=True)
    friends = User.objects.filter(id__in=friend_ids)

    leaderboard = []
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
    leaderboard = sorted(leaderboard, key=lambda x: x['ratio'], reverse=True)

    # 7-Day Performance Metric Graph Generation (Using safe net_hydration properties)
    history_logs = []
    for i in range(6, -1, -1):
        day = today - timezone.timedelta(days=i)
        day_logs = HydrationLog.objects.filter(user=request.user, timestamp__date=day)
        history_logs.append(round(max(0.0, sum(log.net_hydration for log in day_logs)), 2))

    unread_nudges = Nudge.objects.filter(receiver=request.user, is_read=False).select_related('sender')

    context = {
        'profile': profile,
        'current_intake': round(profile.current_intake, 2),
        'leaderboard': leaderboard,
        'history_logs': json.dumps(history_logs),
        'unread_nudges': unread_nudges,
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

            profile = request.user.profile

            log = HydrationLog.objects.create(
                user=request.user,
                amount=amount,
                beverage_type=bev_type
            )

            try:
                active_challenges = GroupChallenge.objects.filter(
                    group__members=request.user,
                    is_active=True,
                    end_date__gte=timezone.localdate()
                )
                for challenge in active_challenges:
                    challenge.current_volume = round(challenge.current_volume + log.net_hydration, 2)
                    challenge.save()
            except Exception as table_err:
                print(f"Group challenge update skipped: {table_err}")

            today = timezone.localdate()
            if profile.current_intake >= profile.daily_goal and profile.last_streak_date != today:
                profile.streak += 1
                profile.last_streak_date = today
                profile.save()

                if hasattr(profile, 'check_and_award_achievements'):
                    profile.check_and_award_achievements()

            return JsonResponse({
                'status': 'success',
                'current_intake': round(profile.current_intake, 2),
                'streak': profile.streak
            })

        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'error_type': type(e).__name__,
                'message': str(e),
                'traceback': traceback.format_exc()
            }, status=500)

    return JsonResponse({'status': 'invalid method'}, status=400)


@login_required
@csrf_exempt
def update_profile_api(request):
    """Saves user fluid parameters and custom hardware container limits via JSON payload"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            profile = request.user.profile

            profile.weight = float(data.get('weight', profile.weight))
            profile.activity_level = float(data.get('activity', profile.activity_level))
            profile.climate_factor = float(data.get('climate', profile.climate_factor))
            profile.custom_volume_label = data.get('custom_volume_label', profile.custom_volume_label)[:30]

            # Handle manual override values if passed via JSON api target
            if 'custom_goal_override' in data:
                val = data.get('custom_goal_override')
                profile.custom_goal_override = float(val) if val else None

            custom_vol = float(data.get('custom_ml', profile.custom_volume))
            if custom_vol > 10:  # Unit normalization guardrail
                custom_vol = custom_vol / 1000.0
            profile.custom_volume = custom_vol

            profile.update_daily_goal()
            return JsonResponse({'status': 'success', 'daily_goal': profile.daily_goal})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'invalid method'}, status=400)


@login_required
def add_friend(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        try:
            target_user = User.objects.get(username=username)
            if target_user != request.user:
                Friendship.objects.get_or_create(from_user=request.user, to_user=target_user)
                Friendship.objects.get_or_create(from_user=target_user, to_user=request.user)
        except User.DoesNotExist:
            pass
    return redirect('index')


@login_required
def profile_view(request):
    profile = request.user.profile

    if request.method == "POST":
        try:
            profile.weight = float(request.POST.get('weight', profile.weight))
            profile.height = float(request.POST.get('height', profile.height))
            profile.age = int(request.POST.get('age', profile.age))
            profile.gender = request.POST.get('gender', profile.gender)
            profile.activity_level = float(request.POST.get('activity', profile.activity_level))
            profile.climate_factor = float(request.POST.get('climate', profile.climate_factor))
            profile.custom_volume = float(request.POST.get('custom_ml', profile.custom_volume))
            profile.custom_volume_label = request.POST.get('custom_volume_label', profile.custom_volume_label)[:30]
            profile.theme_preference = request.POST.get('theme', profile.theme_preference)

            override_val = request.POST.get('custom_goal_override')
            if override_val and str(override_val).strip():
                profile.custom_goal_override = float(override_val)
            else:
                profile.custom_goal_override = None

            if 'profile_picture' in request.FILES:
                profile.profile_picture = request.FILES['profile_picture']

            profile.update_daily_goal()
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

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

            url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m"
            req = urllib.request.Request(url, headers={'User-Agent': 'HydrateCorePro/1.0'})

            with urllib.request.urlopen(req) as response:
                weather_data = json.loads(response.read().decode())
                current_temp = weather_data['current']['temperature_2m']

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
    """🌟 UPDATED: Dispatches contextual targeted social payloads matching chosen intent vibes"""
    if request.method == 'POST':
        try:
            receiver = User.objects.get(username=username)
            is_friend = Friendship.objects.filter(from_user=request.user, to_user=receiver).exists()
            if not is_friend:
                return JsonResponse({'status': 'error', 'message': 'Not friends'}, status=400)

            # Safely catch potential JSON payloads from custom wheel components
            try:
                data = json.loads(request.body or '{}')
                vibe = data.get('vibe', 'friendly')
            except Exception:
                vibe = 'friendly'

            Nudge.objects.create(sender=request.user, receiver=receiver, vibe=vibe)
            return JsonResponse({'status': 'success', 'vibe': vibe})
        except User.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'User not found'}, status=404)
    return JsonResponse({'status': 'invalid method'}, status=400)


@csrf_exempt
@login_required
def dismiss_nudges_api(request):
    if request.method in ['POST', 'GET']:
        if not request.user.is_authenticated:
            return JsonResponse({'status': 'error', 'message': 'User session expired.'}, status=401)

        updated_count = Nudge.objects.filter(receiver=request.user, is_read=False).update(is_read=True)
        return JsonResponse({
            'status': 'success',
            'message': f'Successfully dismissed {updated_count} nudges.'
        })
    return JsonResponse({'status': 'invalid method'}, status=400)


@login_required
def check_new_nudges_api(request):
    if request.method in ['GET', 'POST']:
        unread_nudges = Nudge.objects.filter(receiver=request.user, is_read=False).select_related('sender')

        nudge_list = []
        for nudge in unread_nudges:
            nudge_list.append({
                'id': nudge.id,
                'sender': nudge.sender.username,
                'vibe': nudge.vibe
            })

        return JsonResponse({
            'status': 'success',
            'unread_count': len(nudge_list),
            'nudges': nudge_list
        })
    return JsonResponse({'status': 'invalid method'}, status=400)


@login_required
def use_rescue_api(request):
    if request.method == 'POST':
        profile = request.user.profile
        if profile.streak_rescues > 0:
            profile.streak_rescues -= 1
            profile.last_streak_date = timezone.localdate()
            if profile.streak == 0:
                profile.streak = 1
            profile.save()
            return JsonResponse({'status': 'success', 'rescues': profile.streak_rescues, 'streak': profile.streak})
        return JsonResponse({'status': 'error', 'message': 'No rescues left!'}, status=400)


@login_required
def join_group_api(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        group_name = data.get('group_name', '').strip()
        if not group_name:
            return JsonResponse({'status': 'error', 'message': 'Group name cannot be empty'}, status=400)

        group, created = HydrationGroup.objects.get_or_create(name=group_name)
        group.members.add(request.user)

        if created:
            GroupChallenge.objects.create(
                group=group,
                title=f"First Team Goal: {group_name}",
                target_volume=50.0,
                end_date=timezone.localdate() + timedelta(days=7)
            )

        return JsonResponse({'status': 'success', 'group_name': group.name})


@login_required
def analytics_data_api(request, range_type):
    """Advanced Double Dataset Graph Analytics Pipeline Endpoint"""
    try:
        today = timezone.localdate()

        if range_type == 'weekly':
            start_date = today - timedelta(days=6)
            logs = HydrationLog.objects.filter(
                user=request.user,
                timestamp__date__range=[start_date, today]
            ).annotate(date=TruncDate('timestamp')) \
                .values('date') \
                .annotate(total_raw=Sum('amount'), total_net=Sum('net_hydration')) \
                .order_by('date')

            raw_map = {start_date + timedelta(days=i): 0.0 for i in range(7)}
            net_map = {start_date + timedelta(days=i): 0.0 for i in range(7)}

        elif range_type == 'monthly':
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

            return JsonResponse({'labels': labels, 'raw_data': raw_data, 'net_data': net_data})

        else:
            return JsonResponse({'status': 'error', 'message': 'Invalid range'}, status=400)

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

    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'traceback': traceback.format_exc()
        }, status=500)