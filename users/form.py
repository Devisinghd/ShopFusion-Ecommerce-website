from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django import forms
from .models import UserProfile

class CreateUserForm(UserCreationForm):
    email = forms.EmailField(widget=forms.EmailInput(attrs={"placeholder":"example@gmail.com"}))
    password1 = forms.CharField(widget=forms.PasswordInput(attrs={"placeholder":"Enter Password"}))
    password2 = forms.CharField(widget=forms.PasswordInput(attrs={"placeholder":"Confirm Password"}))

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']
        
        widgets = {
            'username': forms.TextInput(attrs={"placeholder": "Enter Username"}),
            'email': forms.EmailInput(attrs={"placeholder": "example@gmail.com"}),
        }

    def __init__(self, *args, **kwargs):
        super(CreateUserForm, self).__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'w-full rounded-lg border border-gray-300 px-3 py-2 focus:border-blue-500 focus:ring focus:ring-blue-200 focus:ring-opacity-50'})

class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={"placeholder": "Enter Username"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"placeholder": "Enter Password"}))
    def __init__(self, *args, **kwargs):
        super(LoginForm, self).__init__(*args, **kwargs)
        widget_attrs = {
            'class': 'w-full rounded-lg border border-slate-200 px-3 py-2 text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200',
        }
        for field in self.fields.values():
            field.widget.attrs.update(widget_attrs)


class EmailVerificationForm(forms.Form):
    code = forms.CharField(
        label='Verification code',
        min_length=6,
        max_length=6,
        strip=True,
        widget=forms.TextInput(attrs={
            'inputmode': 'numeric',
            'autocomplete': 'one-time-code',
            'placeholder': 'Enter 6-digit code',
        }),
    )

    def clean_code(self):
        code = self.cleaned_data['code']
        if not code.isdigit():
            raise forms.ValidationError('Enter the six-digit code from your email.')
        return code
            


class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={"autocomplete": "given-name"}),
            'last_name': forms.TextInput(attrs={"autocomplete": "family-name"}),
            'email': forms.EmailInput(attrs={"autocomplete": "email"}),
        }

    def __init__(self, *args, **kwargs):
        super(UserUpdateForm, self).__init__(*args, **kwargs)
        self.fields['first_name'].label = 'First name'
        self.fields['last_name'].label = 'Last name'
        self.fields['email'].label = 'Email address'
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'profile-field-input'})


class PersonalInformationForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name']
        widgets = {
            'first_name': forms.TextInput(attrs={"autocomplete": "given-name"}),
            'last_name': forms.TextInput(attrs={"autocomplete": "family-name"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].label = 'First name'
        self.fields['last_name'].label = 'Last name'
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'profile-field-input'})


class EmailAddressForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['email']
        widgets = {
            'email': forms.EmailInput(attrs={"autocomplete": "email"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].label = 'Email address'
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'profile-field-input'})


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['phone_number', 'gender']
        widgets = {
            'phone_number': forms.TelInput(attrs={
                'autocomplete': 'tel',
                'placeholder': 'Add a phone number',
            }),
            'gender': forms.RadioSelect,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['phone_number'].label = 'Mobile number'
        self.fields['gender'].label = 'Your gender'
        self.fields['gender'].choices = [
            ('', 'Prefer not to say') if not value else (value, label)
            for value, label in self.fields['gender'].choices
        ]
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'profile-field-input'})
