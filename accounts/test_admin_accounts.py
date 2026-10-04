import io
import zipfile

import pyotp
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent

from . import two_factor
from .models import User

PASSWORD = "a-long-test-password"


def make_user(email, role=User.Role.ADMIN):
    return User.objects.create_user(
        email=email, password=PASSWORD, first_name=email[:3].title(), last_name="T", role=role,
        email_verified_at=timezone.now(),
    )  # fmt: skip


class AdministratorScreenTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_user("admin@example.org")
        self.client.force_login(self.admin)

    def test_adding_an_administrator_emails_a_set_password_link(self):
        self.client.post(
            reverse("accounts:admin_create"), {"first_name": "Riley", "last_name": "New", "email": "Riley@Example.org"}
        )
        new = User.objects.get(email="riley@example.org")
        self.assertEqual(new.role, User.Role.ADMIN)
        self.assertFalse(new.has_usable_password())
        self.assertFalse(new.is_staff)  # the back office stays limited to a few people
        self.assertIn("/account/password/reset/", mail.outbox[-1].body)
        self.assertTrue(AuditEvent.objects.filter(action="account.admin_added", actor=self.admin).exists())
        # The link really lets them choose a password.
        link = next(line for line in mail.outbox[-1].body.splitlines() if "/password/reset/" in line)
        path = link.split("osea", 1)[-1] if "osea" in link else link[link.index("/account") :]
        self.client.logout()
        response = self.client.get(path, follow=True)
        self.assertContains(response, "Choose a new password")

    def test_existing_accounts_cannot_be_added_again(self):
        make_user("coach@example.org", User.Role.COACH)
        response = self.client.post(
            reverse("accounts:admin_create"), {"first_name": "C", "last_name": "C", "email": "coach@example.org"}
        )
        self.assertContains(response, "already has an account")

    def test_cannot_turn_off_yourself_or_the_last_administrator(self):
        self.client.post(reverse("accounts:admin_set_active", args=[self.admin.pk]), {"active": "0"})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        other = make_user("other@example.org")
        self.client.post(reverse("accounts:admin_set_active", args=[other.pk]), {"active": "0"})
        other.refresh_from_db()
        self.assertFalse(other.is_active)

    def test_resetting_someone_elses_two_step_needs_a_reason(self):
        other = make_user("other@example.org")
        device = two_factor.start_setup(other)
        two_factor.confirm_setup(device, pyotp.TOTP(device.secret).now())
        url = reverse("accounts:admin_reset_two_step", args=[other.pk])
        self.client.post(url, {"reason": ""})
        self.assertTrue(two_factor.is_enabled(other))
        self.client.post(url, {"reason": "Lost phone"})
        self.assertFalse(two_factor.is_enabled(other))
        self.assertTrue(AuditEvent.objects.filter(action="account.two_factor_off", actor=self.admin).exists())

    def test_coaches_cannot_use_these_pages(self):
        coach = make_user("coach@example.org", User.Role.COACH)
        self.client.force_login(coach)
        for method, url in [
            ("get", reverse("accounts:admin_list")),
            ("post", reverse("accounts:admin_create")),
            ("post", reverse("accounts:admin_set_active", args=[self.admin.pk])),
            ("post", reverse("accounts:admin_reset_two_step", args=[self.admin.pk])),
            ("get", reverse("schools:export_everything")),
        ]:
            with self.subTest(url=url):
                response = getattr(self.client, method)(
                    url, {"email": "x@example.org", "first_name": "x", "last_name": "x", "active": "0", "reason": "x"}
                )
                self.assertEqual(response.status_code, 403)
        self.assertEqual(User.objects.filter(role=User.Role.ADMIN).count(), 1)


class FullExportTests(TestCase):
    def test_everything_export_contains_every_table_and_is_logged(self):
        admin = make_user("admin@example.org")
        self.client.force_login(admin)
        response = self.client.get(reverse("schools:export_everything"))
        self.assertEqual(response["Content-Type"], "application/zip")
        names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
        for expected in [
            "schools.csv",
            "people.csv",
            "students.csv",
            "rosters.csv",
            "matches.csv",
            "activity_log.csv",
            "README.txt",
        ]:
            self.assertIn(expected, names)
        self.assertTrue(AuditEvent.objects.filter(action="export.downloaded", actor=admin).exists())


class SecurityHeaderTests(TestCase):
    def test_pages_carry_a_content_security_policy(self):
        response = self.client.get(reverse("core:home"))
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertNotIn("<script>", response.content.decode())  # no inline scripts to allow
