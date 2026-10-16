from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.core import mail
from django.test import override_settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from .models import EmailVerificationCode, UserProfile


class ProfileViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="profileviewer",
            email="profileviewer@example.com",
            password="strong-pass-123",
        )
        self.client.force_login(self.user)

    def test_profile_view_renders_profile_page(self):
        response = self.client.get(reverse("profile-view", kwargs={"id": self.user.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Profile information")
        self.assertContains(response, "Personal information")
        self.assertContains(response, "Email address")
        self.assertContains(response, "Mobile number")
        self.assertContains(response, "?edit=personal")
        self.assertContains(response, "?edit=email")
        self.assertContains(response, "?edit=phone")
        self.assertNotContains(response, 'name="first_name"')
        self.assertNotContains(response, 'name="phone_number"')
        self.assertTrue(UserProfile.objects.filter(user=self.user).exists())

    def test_profile_view_saves_personal_and_contact_details(self):
        response = self.client.post(
            reverse("profile-view", kwargs={"id": self.user.pk}),
            {
                "section": "personal",
                "first_name": "Taylor",
                "last_name": "Morgan",
                "gender": UserProfile.Gender.PREFER_NOT_TO_SAY,
            },
        )

        self.assertRedirects(response, reverse("profile-view", kwargs={"id": self.user.pk}))
        self.user.refresh_from_db()
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(self.user.first_name, "Taylor")
        self.assertEqual(self.user.last_name, "Morgan")
        self.assertEqual(profile.gender, UserProfile.Gender.PREFER_NOT_TO_SAY)

    def test_profile_sections_save_independently(self):
        profile_url = reverse("profile-view", kwargs={"id": self.user.pk})

        email_response = self.client.post(
            profile_url,
            {"section": "email", "email": "updated@example.com"},
        )
        self.assertRedirects(email_response, profile_url)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "updated@example.com")

        phone_response = self.client.post(
            profile_url,
            {"section": "phone", "phone_number": "+1 415 555 0100"},
        )
        self.assertRedirects(phone_response, profile_url)
        self.assertEqual(
            UserProfile.objects.get(user=self.user).phone_number,
            "+1 415 555 0100",
        )

    def test_edit_query_opens_only_the_requested_section(self):
        response = self.client.get(
            reverse("profile-view", kwargs={"id": self.user.pk}) + "?edit=email"
        )

        self.assertContains(response, 'name="email"')
        self.assertNotContains(response, 'name="first_name"')
        self.assertNotContains(response, 'name="phone_number"')

    def test_profile_view_does_not_show_another_users_details(self):
        other_user = get_user_model().objects.create_user(
            username="privateprofile",
            email="private@example.com",
        )

        response = self.client.get(reverse("profile-view", kwargs={"id": other_user.pk}))

        self.assertRedirects(response, reverse("profile-view", kwargs={"id": self.user.pk}))


@override_settings(EMAIL_VERIFICATION=True, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailOtpVerificationTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_registration_sends_otp_instead_of_link(self):
        response = self.client.post(reverse('register'), {
            'username': 'otpuser',
            'email': 'otpuser@example.com',
            'password1': 'strong-pass-123',
            'password2': 'strong-pass-123',
        })

        self.assertRedirects(response, reverse('email-verification-sent'))
        self.assertFalse(get_user_model().objects.get(username='otpuser').is_active)
        self.assertEqual(len(mail.outbox), 1)
        self.assertRegex(mail.outbox[0].body, r'\b\d{6}\b')
        self.assertNotIn('email-verification/', mail.outbox[0].body)

    def test_valid_otp_activates_user_once(self):
        user = get_user_model().objects.create_user(
            username='pendingotp',
            email='pendingotp@example.com',
            password='strong-pass-123',
            is_active=False,
        )
        code = '123456'
        EmailVerificationCode.objects.create(
            user=user,
            code_hash=make_password(code),
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        session = self.client.session
        session['pending_verification_user_id'] = user.pk
        session.save()

        response = self.client.post(reverse('email-verification'), {'code': code})

        self.assertRedirects(response, reverse('email-verification-success'))
        self.assertTrue(get_user_model().objects.get(pk=user.pk).is_active)
        self.assertFalse(EmailVerificationCode.objects.filter(user=user).exists())

    def test_expired_otp_does_not_activate_user(self):
        user = get_user_model().objects.create_user(
            username='expiredotp',
            email='expiredotp@example.com',
            password='strong-pass-123',
            is_active=False,
        )
        EmailVerificationCode.objects.create(
            user=user,
            code_hash=make_password('123456'),
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        session = self.client.session
        session['pending_verification_user_id'] = user.pk
        session.save()

        response = self.client.post(reverse('email-verification'), {'code': '123456'})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.get(pk=user.pk).is_active)
        self.assertContains(response, 'invalid or expired')

    def test_otp_is_invalidated_after_five_incorrect_attempts(self):
        user = get_user_model().objects.create_user(
            username='lockedotp',
            email='lockedotp@example.com',
            password='strong-pass-123',
            is_active=False,
        )
        EmailVerificationCode.objects.create(
            user=user,
            code_hash=make_password('123456'),
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        session = self.client.session
        session['pending_verification_user_id'] = user.pk
        session.save()

        for _ in range(5):
            response = self.client.post(reverse('email-verification'), {'code': '000000'})

        self.assertContains(response, 'Too many incorrect attempts')
        self.assertFalse(EmailVerificationCode.objects.filter(user=user).exists())
        self.assertFalse(get_user_model().objects.get(pk=user.pk).is_active)

    def test_login_throttles_repeated_invalid_credentials(self):
        responses = [
            self.client.post(reverse('login'), {'username': 'unknown-user', 'password': 'wrong'})
            for _ in range(10)
        ]
        self.assertTrue(all(response.status_code == 200 for response in responses))

        blocked = self.client.post(
            reverse('login'),
            {'username': 'unknown-user', 'password': 'wrong'},
        )

        self.assertEqual(blocked.status_code, 429)

    def test_logout_requires_post(self):
        user = get_user_model().objects.create_user(
            username='logoutuser',
            password='strong-pass-123',
        )
        self.client.force_login(user)

        response = self.client.get(reverse('logout'))

        self.assertRedirects(response, reverse('index'))
        self.assertTrue(self.client.session.get('_auth_user_id'))

        self.client.post(reverse('logout'))
        self.assertNotIn('_auth_user_id', self.client.session)
