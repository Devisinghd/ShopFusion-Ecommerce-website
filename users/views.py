import logging
import secrets
import hashlib

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.shortcuts import redirect, render
from .form import (
    CreateUserForm,
    EmailAddressForm,
    EmailVerificationForm,
    PersonalInformationForm,
    UserProfileForm,
    UserUpdateForm,
)
from django.template.loader import render_to_string
from django.contrib.auth.models import User
from django.db import transaction
from .form import LoginForm
from .models import EmailVerificationCode, UserProfile
from django.contrib.auth import authenticate,login,logout
from django.contrib.auth.decorators import login_required

logger = logging.getLogger(__name__)
# Create your views here.

def register(request):
    if request.user.is_authenticated:
        return redirect('index')
    form = CreateUserForm()
    if request.method == 'POST':
        form = CreateUserForm(request.POST or None)
        if form.is_valid():
            user = form.save(commit=False)
            if not settings.EMAIL_VERIFICATION:
                user.is_active = True
                user.save()
                messages.success(request, 'Account created successfully. You may now log in.')
                return redirect('login')

            user.is_active = False

            try:
                verification_code = f'{secrets.randbelow(1_000_000):06d}'
                with transaction.atomic():
                    user.save()
                    EmailVerificationCode.objects.update_or_create(
                        user=user,
                        defaults={
                            'code_hash': make_password(verification_code),
                            'expires_at': EmailVerificationCode.expiry_time(settings.EMAIL_OTP_EXPIRY_MINUTES),
                            'attempts': 0,
                        },
                    )

                    html_message = render_to_string('users/email-verification.html', {
                        'user': user,
                        'verification_code': verification_code,
                        'expiry_minutes': settings.EMAIL_OTP_EXPIRY_MINUTES,
                    })
                    plain_message = (
                        f'Hi {user.username}, your ShopFusion email verification code is '
                        f'{verification_code}. It expires in {settings.EMAIL_OTP_EXPIRY_MINUTES} minutes.'
                    )
                    user.email_user(
                        subject='Your ShopFusion email verification code',
                        message=plain_message,
                        html_message=html_message,
                        fail_silently=False,
                    )

                request.session['pending_verification_user_id'] = user.pk
                messages.success(request, 'Account created successfully. Check your email to activate the account.')
                return redirect('email-verification-sent')
            except Exception:
                logger.exception('Failed to render/send verification email for user %s.', user.username)
                messages.error(request, 'We could not send the verification code. Please try again later.')
                return redirect('register')

    return render(request,'users/register.html', {'form': form})


def email_verification(request):
    user_id = request.session.get('pending_verification_user_id')
    user = User.objects.filter(pk=user_id, is_active=False).first()
    if user is None:
        return redirect('email-verification-failed')

    form = EmailVerificationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        verification = EmailVerificationCode.objects.filter(user=user).first()
        if verification and verification.is_expired():
            verification.delete()
            form.add_error('code', 'That code is invalid or expired.')
        elif verification and verification.attempts >= 5:
            verification.delete()
            form.add_error('code', 'Too many incorrect attempts. Register again to receive a new code.')
        elif verification and check_password(form.cleaned_data['code'], verification.code_hash):
            user.is_active = True
            user.save(update_fields=['is_active'])
            verification.delete()
            request.session.pop('pending_verification_user_id', None)
            return redirect('email-verification-success')
        else:
            if verification:
                verification.attempts += 1
                if verification.attempts >= 5:
                    verification.delete()
                    form.add_error('code', 'Too many incorrect attempts. Register again to receive a new code.')
                else:
                    verification.save(update_fields=['attempts'])
                    form.add_error('code', 'That code is invalid or expired.')
            else:
                form.add_error('code', 'That code is invalid or expired.')

    return render(request, 'users/email-verification-sent.html', {
        'form': form,
        'expiry_minutes': settings.EMAIL_OTP_EXPIRY_MINUTES,
    })

def email_verification_sent(request):
    return email_verification(request)

def email_verification_success(request):
    return render(request,'users/email-verification-success.html')

def email_verification_failed(request):
    return render(request,'users/email-verification-failed.html')

def user_login(request):
    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        username = request.POST.get('username', '').strip().casefold()
        remote_addr = request.META.get('REMOTE_ADDR', '')
        throttle_key = 'login:' + hashlib.sha256(
            f'{remote_addr}:{username}'.encode('utf-8')
        ).hexdigest()
        if cache.get(throttle_key, 0) >= settings.LOGIN_THROTTLE_LIMIT:
            form.add_error(None, 'Too many sign-in attempts. Please wait and try again.')
            return render(request, 'users/login.html', {'form': form}, status=429)
        if form.is_valid():
            cache.delete(throttle_key)
            login(request, form.get_user())
            return redirect('index')
        if not cache.add(throttle_key, 1, timeout=settings.LOGIN_THROTTLE_SECONDS):
            try:
                cache.incr(throttle_key)
            except ValueError:
                cache.set(throttle_key, 1, timeout=settings.LOGIN_THROTTLE_SECONDS)
    else:
        form = LoginForm()
    return render(request, 'users/login.html', {'form': form})


def user_logout(request):
    if request.method != 'POST':
        return redirect('index')
    logout(request)
    return render(request,'users/logout-confirmation.html')


@login_required
def profile(request):
    if request.method == 'POST':
        user_form = UserUpdateForm(request.POST, instance=request.user)
        if user_form.is_valid():
            user_form.save()
            return redirect('index')
    else:
        user_form = UserUpdateForm(instance=request.user)

    return render(request,'users/profile.html',{'user_form':user_form})

@login_required
def profile_view(request,id):
    if id != request.user.pk:
        return redirect('profile-view', id=request.user.pk)

    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)
    personal_form = PersonalInformationForm(instance=user)
    email_form = EmailAddressForm(instance=user)
    profile_form = UserProfileForm(instance=profile)
    editing_section = request.GET.get('edit', '')
    if editing_section not in {'personal', 'email', 'phone'}:
        editing_section = ''

    if request.method == 'POST':
        editing_section = request.POST.get('section', '')
        if editing_section == 'personal':
            personal_form = PersonalInformationForm(request.POST, instance=user)
            profile_form = UserProfileForm(request.POST, instance=profile)
            personal_form_valid = personal_form.is_valid()
            profile_form_valid = profile_form.is_valid()
            section_is_valid = personal_form_valid and profile_form_valid
        elif editing_section == 'email':
            email_form = EmailAddressForm(request.POST, instance=user)
            section_is_valid = email_form.is_valid()
        elif editing_section == 'phone':
            profile_form = UserProfileForm(request.POST, instance=profile)
            section_is_valid = profile_form.is_valid()
        else:
            messages.error(request, 'Choose a profile section to update.')
            return redirect('profile-view', id=user.pk)

        if section_is_valid:
            with transaction.atomic():
                if editing_section == 'personal':
                    personal_form.save()
                    profile_form.save()
                elif editing_section == 'email':
                    email_form.save()
                else:
                    profile_form.save()
            messages.success(request, 'Your profile details have been updated.')
            return redirect('profile-view', id=user.pk)
        messages.error(request, 'Please correct the highlighted details.')

    return render(request, 'users/profile-view.html', {
        'user': user,
        'personal_form': personal_form,
        'email_form': email_form,
        'profile_form': profile_form,
        'profile': profile,
        'editing_section': editing_section,
    })
