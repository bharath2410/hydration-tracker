from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    weight = models.FloatField(default=70.0)

    # Advanced body metrics
    height = models.FloatField(default=170.0)  # in cm
    age = models.IntegerField(default=25)

    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other'),
    ]
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, default='M')

    activity_level = models.FloatField(default=0.0)
    climate_factor = models.FloatField(default=0.0)

    # 🌟 UPDATED: Advanced Container Customization Engine
    custom_volume = models.FloatField(default=0.30)
    custom_volume_label = models.CharField(max_length=30, default='Travel Flask')

    # Optional Manual Goal Override
    custom_goal_override = models.FloatField(null=True, blank=True)  # in Liters
    profile_picture = models.ImageField(upload_to='profile_pics/', null=True, blank=True)
    daily_goal = models.FloatField(default=2.50)
    streak = models.IntegerField(default=0)
    streak_rescues = models.IntegerField(default=1)
    last_streak_date = models.DateField(null=True, blank=True)
    last_decay_time = models.DateTimeField(default=timezone.now)
    theme_preference = models.CharField(max_length=10, default='dark')
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    # Smart algorithm calculation method
    def update_daily_goal(self):
        if self.custom_goal_override is not None:
            self.daily_goal = max(1.0, min(10.0, self.custom_goal_override))
        else:
            calculated = (self.weight * 0.035) + self.activity_level + self.climate_factor
            if self.gender == 'F':
                calculated -= 0.3
            self.daily_goal = max(1.5, min(6.0, calculated))
        self.save()

    @property
    def current_intake(self):
        today = timezone.localdate()
        logs = HydrationLog.objects.filter(user=self.user, timestamp__date=today)
        total = sum(log.net_hydration for log in logs)
        # 🌟 Safety check: If total is negative, return 0.00 so the circle looks clean!
        return max(0.0, round(float(total), 2))

    def check_and_award_achievements(self):
        unlocked_ids = UserAchievement.objects.filter(user=self.user).values_list('achievement_id', flat=True)
        locked_achievements = Achievement.objects.exclude(id__in=unlocked_ids)

        for ach in locked_achievements:
            should_award = False

            if ach.condition_type == 'streak':
                if self.streak >= ach.condition_value:
                    should_award = True

            elif ach.condition_type == 'super_hydrated':
                if self.current_intake >= ach.condition_value:
                    should_award = True

            elif ach.condition_type == 'early_bird':
                today = timezone.localdate()
                early_log_exists = HydrationLog.objects.filter(
                    user=self.user,
                    timestamp__date=today,
                    timestamp__time__lt=timezone.datetime.strptime("09:00:00", "%H:%M:%S").time(),
                    amount__gte=ach.condition_value
                ).exists()
                if early_log_exists:
                    should_award = True

            if should_award:
                UserAchievement.objects.get_or_create(user=self.user, achievement=ach)

    @property
    def avatar_url(self):
        if self.profile_picture and hasattr(self.profile_picture, 'url'):
            try:
                if self.profile_picture.storage.exists(self.profile_picture.name):
                    return self.profile_picture.url
            except Exception:
                pass

        if self.gender == 'F':
            return "https://img.icons8.com/color/96/user-female-circle--v1.png"
        elif self.gender == 'O':
            return "https://img.icons8.com/color/96/user-gender-neutral-backside.png"
        else:
            return "https://img.icons8.com/color/96/user-male-circle--v1.png"


class HydrationLog(models.Model):
    BEVERAGE_CHOICES = [
        ('water', 'Water'),
        ('sports', 'Electrolytes'),
        ('caffeine', 'Coffee/Soda'),
        ('alcohol', 'Alcohol'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='hydration_logs')
    amount = models.FloatField()
    net_hydration = models.FloatField(default=0.0)
    beverage_type = models.CharField(max_length=15, choices=BEVERAGE_CHOICES, default='water')
    modifier = models.FloatField(default=1.0)
    timestamp = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        multipliers = {
            'water': 1.0,
            'sports': 1.2,
            'caffeine': 0.8,
            'alcohol': -0.5
        }
        factor = multipliers.get(self.beverage_type, 1.0)
        self.modifier = factor
        self.net_hydration = round(self.amount * factor, 2)
        super().save(*args, **kwargs)


class HydrationGroup(models.Model):
    name = models.CharField(max_length=100, unique=True)
    members = models.ManyToManyField(User, related_name='hydration_groups')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class GroupChallenge(models.Model):
    group = models.ForeignKey(HydrationGroup, on_delete=models.CASCADE, related_name='challenges')
    title = models.CharField(max_length=150)
    target_volume = models.FloatField()
    current_volume = models.FloatField(default=0.0)
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.title} ({self.group.name})"


class Friendship(models.Model):
    from_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='friendships_initiated')
    to_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='friendships_received')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('from_user', 'to_user')


class Achievement(models.Model):
    title = models.CharField(max_length=100)
    description = models.CharField(max_length=255)
    icon = models.CharField(max_length=50)
    condition_type = models.CharField(max_length=50)
    condition_value = models.FloatField()

    def __str__(self):
        return self.title


class UserAchievement(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='earned_achievements')
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE)
    unlocked_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ('user', 'achievement')


class Nudge(models.Model):
    # 🌟 UPDATED: Social Nudge Context Vibe Configurations
    NUDGE_VIBES = [
        ('friendly', 'Friendly drop (💧)'),
        ('urgent', 'Urgent alert (🚨)'),
        ('challenge', 'Playful challenge (🏆)'),
    ]

    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_nudges')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_nudges')
    timestamp = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    # Track targeted message strings matching intent wheel payload
    vibe = models.CharField(max_length=15, choices=NUDGE_VIBES, default='friendly')

    def __str__(self):
        return f"{self.sender.username} ({self.vibe}) -> {self.receiver.username}"