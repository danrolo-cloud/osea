import pyotp
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent

from . import two_factor
from .models import TwoFactor, User

PASSWORD = "a-long-test-password"


def make_user(email="coach@example.org", role=User.Role.COACH):
    return User.objects.create_user(
        email=email, password=PASSWORD, first_name="Test", last_name="User", role=role, email_verified_at=timezone.now()
    )


class SignInLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()
        self.url = reverse("accounts:login")

    def sign_in(self, password, email="coach@example.org", ip="10.0.0.1"):
        return self.client.post(self.url, {"username": email, "password": password}, REMOTE_ADDR=ip)

    def test_five_wrong_passwords_pause_that_account_even_for_the_right_password(self):
        for _ in range(5):
            self.sign_in("wrong-password")
        response = self.sign_in(PASSWORD)
        self.assertContains(response, "sign-in is paused for 15 minutes")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_other_accounts_are_not_affected(self):
        make_user("other@example.org")
        for _ in range(5):
            self.sign_in("wrong-password")
        response = self.sign_in(PASSWORD, email="other@example.org", ip="10.0.0.2")
        self.assertEqual(response.status_code, 302)

    def test_a_successful_sign_in_resets_the_count(self):
        for _ in range(4):
            self.sign_in("wrong-password")
        self.sign_in(PASSWORD)
        self.client.logout()
        for _ in range(4):
            self.sign_in("wrong-password")
        self.assertEqual(self.sign_in(PASSWORD).status_code, 302)

    def test_one_network_address_is_limited_across_accounts(self):
        for i in range(20):
            self.sign_in("wrong-password", email=f"nobody{i}@example.org")
        response = self.sign_in(PASSWORD)  # right password for a real account, same address
        self.assertContains(response, "sign-in is paused")

    def test_password_reset_requests_are_limited_without_revealing_anything(self):
        for _ in range(5):
            response = self.client.post(reverse("accounts:password_reset"), {"email": "coach@example.org"})
            self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 3)  # only 3 emails per address per hour


class TwoStepSetupTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()
        self.client.force_login(self.user)

    def code(self):
        device = TwoFactor.objects.get(user=self.user)
        return pyotp.TOTP(device.secret).now()

    def test_setup_needs_a_working_code_and_gives_ten_backup_codes(self):
        page = self.client.get(reverse("accounts:two_factor_setup"))
        self.assertContains(page, "<svg")
        self.client.post(reverse("accounts:two_factor_setup"), {"code": "000000"})
        self.assertFalse(two_factor.is_enabled(self.user))
        response = self.client.post(reverse("accounts:two_factor_setup"), {"code": self.code()})
        self.assertRedirects(response, reverse("accounts:backup_codes"), fetch_redirect_response=False)
        self.assertTrue(two_factor.is_enabled(self.user))
        codes_page = self.client.get(reverse("accounts:backup_codes"))
        self.assertEqual(len(codes_page.context["codes"]), 10)
        # Shown once only
        self.assertRedirects(self.client.get(reverse("accounts:backup_codes")), reverse("accounts:profile"))
        self.assertTrue(AuditEvent.objects.filter(action="account.two_factor_on").exists())


class TwoStepSignInTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()
        device = two_factor.start_setup(self.user)
        self.backup = two_factor.confirm_setup(device, pyotp.TOTP(device.secret).now())
        TwoFactor.objects.filter(user=self.user).update(last_used_step=None)
        self.secret = device.secret

    def password_step(self):
        return self.client.post(reverse("accounts:login"), {"username": self.user.email, "password": PASSWORD})

    def test_password_alone_is_not_enough(self):
        response = self.password_step()
        self.assertRedirects(response, reverse("accounts:two_factor_verify"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get(reverse("core:coach_dashboard")).status_code, 302)

    def test_correct_code_signs_in_and_cannot_be_reused(self):
        self.password_step()
        code = pyotp.TOTP(self.secret).now()
        response = self.client.post(reverse("accounts:two_factor_verify"), {"code": code})
        self.assertRedirects(response, reverse("core:dashboard"), fetch_redirect_response=False)
        self.assertIn("_auth_user_id", self.client.session)
        self.client.logout()
        self.password_step()
        self.client.post(reverse("accounts:two_factor_verify"), {"code": code})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_backup_codes_work_once(self):
        self.password_step()
        self.client.post(reverse("accounts:two_factor_verify"), {"code": self.backup[0].upper()})
        self.assertIn("_auth_user_id", self.client.session)
        self.client.logout()
        self.password_step()
        self.client.post(reverse("accounts:two_factor_verify"), {"code": self.backup[0]})
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(two_factor.backup_codes_left(self.user), 9)

    def test_wrong_codes_are_limited(self):
        self.password_step()
        for _ in range(5):
            self.client.post(reverse("accounts:two_factor_verify"), {"code": "123456"})
        response = self.client.post(reverse("accounts:two_factor_verify"), {"code": pyotp.TOTP(self.secret).now()})
        self.assertContains(response, "Too many wrong codes")
        self.assertNotIn("_auth_user_id", self.client.session)


@override_settings(OSEA_REQUIRE_ADMIN_2FA=True)
class AdminTwoStepRequiredTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_user("admin@example.org", User.Role.ADMIN)
        self.client.force_login(self.admin)

    def test_admin_pages_wait_until_two_step_sign_in_is_on(self):
        for url in [reverse("core:admin_dashboard"), reverse("schools:school_list"), "/back-office/"]:
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), reverse("accounts:two_factor_setup"))
        device = two_factor.start_setup(self.admin)
        two_factor.confirm_setup(device, pyotp.TOTP(device.secret).now())
        self.assertEqual(self.client.get(reverse("core:admin_dashboard")).status_code, 200)

    def test_admins_cannot_turn_it_off(self):
        device = two_factor.start_setup(self.admin)
        two_factor.confirm_setup(device, pyotp.TOTP(device.secret).now())
        self.client.post(reverse("accounts:two_factor_off"), {"code": "whatever"})
        self.assertTrue(two_factor.is_enabled(self.admin))

    def test_back_office_sign_in_uses_the_main_sign_in_page(self):
        self.client.logout()
        response = self.client.get("/back-office/login/?next=/back-office/")
        self.assertRedirects(
            response, reverse("accounts:login") + "?next=%2Fback-office%2F", fetch_redirect_response=False
        )


class ResetCommandTests(TestCase):
    def test_reset_command_turns_it_off_and_logs_it(self):
        from io import StringIO

        from django.core.management import call_command

        user = make_user()
        device = two_factor.start_setup(user)
        two_factor.confirm_setup(device, pyotp.TOTP(device.secret).now())
        call_command("reset_two_step", user.email, reason="Lost phone", stdout=StringIO())
        self.assertFalse(two_factor.is_enabled(user))
        self.assertEqual(user.backup_codes.count(), 0)
        self.assertTrue(AuditEvent.objects.filter(action="account.two_factor_off", actor=None).exists())
