from io import StringIO

from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import User

PASSWORD = "a-long-test-password"


def make_user(email="coach@example.org", role=User.Role.COACH, **extra):
    return User.objects.create_user(
        email=email, password=PASSWORD, first_name="Test", last_name="Person", role=role, **extra
    )


class UserModelTests(TestCase):
    def test_email_is_stored_in_lowercase(self):
        user = make_user(email="  Teacher@Example.ORG ")
        self.assertEqual(user.email, "teacher@example.org")

    def test_new_users_are_coaches_by_default(self):
        user = User.objects.create_user(email="x@example.org", password=PASSWORD)
        self.assertEqual(user.role, User.Role.COACH)
        self.assertTrue(user.is_coach)
        self.assertFalse(user.is_osea_admin)
        self.assertFalse(user.is_staff)

    def test_superuser_is_an_osea_admin(self):
        user = User.objects.create_superuser(email="root@example.org", password=PASSWORD)
        self.assertTrue(user.is_osea_admin)
        self.assertTrue(user.is_staff)

    def test_deactivated_user_loses_their_role(self):
        user = make_user(role=User.Role.ADMIN, is_active=False)
        self.assertFalse(user.is_osea_admin)
        self.assertFalse(user.is_coach)


class SignInTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.url = reverse("accounts:login")

    def test_sign_in_with_email_in_any_letter_case(self):
        response = self.client.post(self.url, {"username": "COACH@example.org", "password": PASSWORD})
        self.assertRedirects(response, reverse("core:dashboard"), fetch_redirect_response=False)

    def test_wrong_password_shows_a_helpful_error(self):
        response = self.client.post(self.url, {"username": "coach@example.org", "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "don&#x27;t match an active account")

    def test_deactivated_account_cannot_sign_in(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(self.url, {"username": "coach@example.org", "password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_sign_out_requires_a_form_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.client.post(reverse("accounts:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)


class PasswordResetTests(TestCase):
    def test_known_and_unknown_emails_get_the_same_response(self):
        """The reset page must not reveal whether someone has an account."""
        make_user()
        url = reverse("accounts:password_reset")
        known = self.client.post(url, {"email": "coach@example.org"})
        unknown = self.client.post(url, {"email": "nobody@example.org"})
        self.assertRedirects(known, reverse("accounts:password_reset_done"))
        self.assertRedirects(unknown, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["coach@example.org"])
        self.assertIn("/account/password/reset/", mail.outbox[0].body)


class BackOfficeTests(TestCase):
    def test_coach_cannot_open_back_office(self):
        self.client.force_login(make_user())
        response = self.client.get("/back-office/")
        self.assertRedirects(response, "/back-office/login/?next=/back-office/")

    def test_osea_admin_without_staff_flag_cannot_open_back_office(self):
        self.client.force_login(make_user(email="a@example.org", role=User.Role.ADMIN))
        response = self.client.get("/back-office/")
        self.assertEqual(response.status_code, 302)


class SeedDemoCommandTests(TestCase):
    @override_settings(DEBUG=False)
    def test_refuses_outside_development(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo")
        self.assertFalse(User.objects.exists())

    @override_settings(DEBUG=True)
    def test_creates_demo_accounts_and_can_run_twice(self):
        call_command("seed_demo", stdout=StringIO())
        call_command("seed_demo", stdout=StringIO())
        self.assertEqual(User.objects.count(), 2)
        self.assertTrue(User.objects.get(email="admin@example.org").is_osea_admin)
        self.assertTrue(User.objects.get(email="coach@example.org").is_coach)
