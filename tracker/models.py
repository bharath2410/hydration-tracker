from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    weight = models.FloatField(default=70.0)
    activity_level = models.FloatField(default=0.0)
    climate_factor = models.FloatField(default=0.0)
    custom_volume = models.FloatField(default=0.40) # in Liters
    daily_goal = models.FloatField(default=2.50)
    streak = models.IntegerField(default=0)
    last_streak_date = models.DateField(null=True, blank=True)
    last_decay_time = models.DateTimeField(default=timezone.now)
    theme_preference = models.CharField(max_length=10, default='dark')

    def update_daily_goal(self):
        calculated = (self.weight * 0.035) + self.activity_level + self.climate_factor
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