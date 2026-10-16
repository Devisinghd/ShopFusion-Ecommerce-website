from datetime import timedelta

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class EmailVerificationCode(models.Model):
	user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='email_verification_code')
	code_hash = models.CharField(max_length=128)
	expires_at = models.DateTimeField()
	attempts = models.PositiveSmallIntegerField(default=0)
	created_at = models.DateTimeField(auto_now_add=True)

	def is_expired(self):
		return timezone.now() >= self.expires_at

	@classmethod
	def expiry_time(cls, minutes=10):
		return timezone.now() + timedelta(minutes=minutes)


class UserProfile(models.Model):
	class Gender(models.TextChoices):
		MALE = 'male', 'Male'
		FEMALE = 'female', 'Female'
		OTHER = 'other', 'Other'
		PREFER_NOT_TO_SAY = 'prefer_not_to_say', 'Prefer not to say'

	user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
	phone_number = models.CharField(max_length=20, blank=True)
	gender = models.CharField(max_length=20, choices=Gender.choices, blank=True)

	def __str__(self):
		return f'{self.user.username} profile'
