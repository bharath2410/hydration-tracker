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
        total = sum(log.amount for log in logs)
        return max(0.0, total)

class HydrationLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='hydration_logs')
    amount = models.FloatField() # Positive for drinks, negative for decay/sweat
    timestamp = models.DateTimeField(default=timezone.now)

class Friendship(models.Model):
    from_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='friendships_initiated')
    to_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='friendships_received')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('from_user', 'to_user')