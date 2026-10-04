from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import manage_views, views

app_name = "accounts"

urlpatterns = [
    path("sign-in/", views.SignInView.as_view(), name="login"),
    path("administrators/", manage_views.admin_list, name="admin_list"),
    path("administrators/new/", manage_views.admin_create, name="admin_create"),
    path("administrators/<int:pk>/active/", manage_views.admin_set_active, name="admin_set_active"),
    path("people/<int:pk>/reset-two-step/", manage_views.admin_reset_two_step, name="admin_reset_two_step"),
    path("sign-in/code/", views.two_factor_verify, name="two_factor_verify"),
    path("two-step/", views.two_factor_setup, name="two_factor_setup"),
    path("two-step/backup-codes/", views.backup_codes, name="backup_codes"),
    path("two-step/backup-codes/renew/", views.backup_codes_renew, name="backup_codes_renew"),
    path("two-step/off/", views.two_factor_off, name="two_factor_off"),
    path("sign-out/", auth_views.LogoutView.as_view(), name="logout"),
    path("sign-up/", views.sign_up, name="sign_up"),
    path("verify/<str:token>/", views.verify_email, name="verify_email"),
    path("verify-resend/", views.resend_verification, name="resend_verification"),
    path("", views.profile, name="profile"),
    path(
        "password/change/",
        auth_views.PasswordChangeView.as_view(
            template_name="accounts/password_change.html",
            success_url=reverse_lazy("accounts:password_change_done"),
        ),
        name="password_change",
    ),
    path(
        "password/change/done/",
        auth_views.PasswordChangeDoneView.as_view(template_name="accounts/password_change_done.html"),
        name="password_change_done",
    ),
    path(
        "password/reset/",
        views.LimitedPasswordResetView.as_view(
            template_name="accounts/password_reset.html",
            email_template_name="accounts/emails/password_reset.txt",
            subject_template_name="accounts/emails/password_reset_subject.txt",
            success_url=reverse_lazy("accounts:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password/reset/sent/",
        auth_views.PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "password/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("accounts:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "password/reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(template_name="accounts/password_reset_complete.html"),
        name="password_reset_complete",
    ),
]
