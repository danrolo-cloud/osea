from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserChangeForm, UserCreationForm

from .models import User


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )

    error_messages = {
        "invalid_login": "That email and password don't match an active account. Check both and try again.",
        "inactive": "This account has been turned off. Contact OSEA if you think this is a mistake.",
    }


class AdminUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "role"]


class AdminUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"
