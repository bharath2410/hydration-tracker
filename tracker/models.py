from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    weight = models.FloatField(default=70.0)

    # 🌟 NEW: Advanced body metrics
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
    custom_volume = models.FloatField(default=0.40)  # in Liters

    # 🌟 NEW: Optional Manual Goal Override
    custom_goal_override = models.FloatField(null=True, blank=True)  # in Liters
    profile_picture = models.ImageField(upload_to='profile_pics/', null=True, blank=True)
    daily_goal = models.FloatField(default=2.50)
    streak = models.IntegerField(default=0)
    last_streak_date = models.DateField(null=True, blank=True)
    last_decay_time = models.DateTimeField(default=timezone.now)
    theme_preference = models.CharField(max_length=10, default='dark')
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    # 🌟 UPDATED: Smart algorithm calculation method
    def update_daily_goal(self):
        # If the user has a manual override, prioritize it
        if self.custom_goal_override is not None:
            self.daily_goal = max(1.0, min(10.0, self.custom_goal_override))
        else:
            # Baseline calculation: 35ml per kg of body weight
            calculated = (self.weight * 0.035) + self.activity_level + self.climate_factor

            # Gender correction adjustments
            if self.gender == 'F':
                calculated -= 0.3  # Female baseline adjustment factor

            # Clamp the calculation between healthy safety guardrails
            self.daily_goal = max(1.5, min(6.0, calculated))

        self.save()

    @property
    def current_intake(self):
        today = timezone.localdate()
        logs = HydrationLog.objects.filter(user=self.user, timestamp__date=today)
        # 🌟 UPDATED TO USE THE LOG'S NET HYDRATION:
        total = sum(log.net_hydration for log in logs)
        return max(0.0, total)

    def check_and_award_achievements(self):
        """Evaluates achievements criteria and grants them if conditions are met"""
        # Fetch achievements the user hasn't unlocked yet
        unlocked_ids = UserAchievement.objects.filter(user=self.user).values_list('achievement_id', flat=True)
        locked_achievements = Achievement.objects.exclude(id__in=unlocked_ids)

        for ach in locked_achievements:
            should_award = False

            if ach.condition_type == 'streak':
                if self.streak >= ach.condition_value:
                    should_award = True

            elif ach.condition_type == 'super_hydrated':
                # Reached a milestone volume logged in a single day
                if self.current_intake >= ach.condition_value:
                    should_award = True

            elif ach.condition_type == 'early_bird':
                # Logged a drink early in the morning
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


class HydrationLog(models.Model):
    BEVERAGE_CHOICES = [
        ('water', 'Water'),
        ('sports', 'Electrolytes'),
        ('caffeine', 'Coffee/Soda'),
        ('alcohol', 'Alcohol'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='hydration_logs')
    amount = models.FloatField()  # Base liquid volume in Liters

    # 🌟 NEW FIELDS FOR BEVERAGE TYPES:
    beverage_type = models.CharField(max_length=15, choices=BEVERAGE_CHOICES, default='water')
    modifier = models.FloatField(default=1.0)  # The efficiency scaling factor

    timestamp = models.DateTimeField(default=timezone.now)

    @property
    def net_hydration(self):
        """Calculates the true hydration value added or subtracted"""
        return round(self.amount * self.modifier, 2)

class Friendship(models.Model):
    from_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='friendships_initiated')
    to_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='friendships_received')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('from_user', 'to_user')

class Achievement(models.Model):
    title = models.CharField(max_length=100)
    description = models.CharField(max_length=255)
    icon = models.CharField(max_length=50)  # We will use clean emoji icons!
    condition_type = models.CharField(max_length=50) # 'streak', 'early_bird', 'super_hydrated'
    condition_value = models.FloatField()

    def __str__(self):
        return self.title

class UserAchievement(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='earned_achievements')
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE)
    unlocked_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ('user', 'achievement')