from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from accounts.models import User

PASSWORD = "a-long-test-password"


class RolePermissionTests(TestCase):
    """
    Each protected page must be blocked on the server for the wrong people,
    not just hidden from the menu.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            email="admin@example.org", password=PASSWORD, first_name="A", last_name="Admin", role=User.Role.ADMIN
        )
        cls.coach = User.objects.create_user(
            email="coach@example.org", password=PASSWORD, first_name="C", last_name="Coach", role=User.Role.COACH
        )

    admin_pages = ["core:admin_dashboard", "core:style_guide"]
    coach_pages = ["core:coach_dashboard"]

    def test_signed_out_visitors_are_sent_to_sign_in(self):
        for name in self.admin_pages + self.coach_pages + ["core:dashboard"]:
            with self.subTest(page=name):
                url = reverse(name)
                response = self.client.get(url)
                self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_coach_is_refused_admin_pages(self):
        self.client.force_login(self.coach)
        for name in self.admin_pages:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 403)
                self.assertContains(response, "have access to this page", status_code=403)

    def test_admin_is_refused_coach_pages(self):
        self.client.force_login(self.admin)
        for name in self.coach_pages:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_each_role_can_open_its_own_pages(self):
        for user, pages in [(self.admin, self.admin_pages), (self.coach, self.coach_pages)]:
            self.client.force_login(user)
            for name in pages:
                with self.subTest(user=user.email, page=name):
                    self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_dashboard_link_sends_each_role_to_the_right_place(self):
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get(reverse("core:dashboard")), reverse("core:admin_dashboard"))
        self.client.force_login(self.coach)
        self.assertRedirects(self.client.get(reverse("core:dashboard")), reverse("core:coach_dashboard"))

    def test_coach_menu_does_not_show_admin_links(self):
        self.client.force_login(self.coach)
        response = self.client.get(reverse("core:coach_dashboard"))
        self.assertNotContains(response, reverse("core:admin_dashboard"))
        self.assertNotContains(response, reverse("core:style_guide"))


class PublicPageTests(TestCase):
    def test_home_page_is_public(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Coach sign in")

    def test_health_check(self):
        response = self.client.get(reverse("core:healthz"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")


class SafeEmailTests(TestCase):
    """Fictional (reserved) addresses never reach the real mail server."""

    def test_reserved_addresses(self):
        from core.mail import is_reserved

        for address in ["coach@mvdsb.example", "admin@example.org", "a@mail.example.com", "x@school.test"]:
            self.assertTrue(is_reserved(address), address)
        for address in ["coach@example.ca", "coach@mvdsb.example.ca", "someone@notexample.com", "a@osea.ca"]:
            self.assertFalse(is_reserved(address), address)

    def test_backend_drops_fictional_recipients(self):
        from unittest import mock

        from django.core.mail import EmailMessage
        from django.core.mail.backends.smtp import EmailBackend

        from core.mail import SafeSMTPBackend

        mixed = EmailMessage("Hi", "Body", "platform@osea.ca", ["real@osea.ca", "coach@mvdsb.example"])
        only_fake = EmailMessage("Hi", "Body", "platform@osea.ca", ["coach@mvdsb.example"])
        with mock.patch.object(EmailBackend, "send_messages", return_value=1) as smtp_send:
            sent = SafeSMTPBackend().send_messages([mixed, only_fake])
        self.assertEqual(sent, 1)
        (messages,), _ = smtp_send.call_args
        self.assertEqual(messages, [mixed])
        self.assertEqual(mixed.to, ["real@osea.ca"])

        with mock.patch.object(EmailBackend, "send_messages") as smtp_send:
            self.assertEqual(SafeSMTPBackend().send_messages([only_fake]), 0)
        smtp_send.assert_not_called()


class EnvironmentBannerTests(TestCase):
    def test_live_site_has_no_banner(self):
        with self.settings(OSEA_ENVIRONMENT_LABEL=""):
            self.assertNotContains(self.client.get("/"), "env-banner")

    def test_development_banner_says_emails_are_not_sent(self):
        with self.settings(OSEA_ENVIRONMENT_LABEL="Development"):
            self.assertContains(self.client.get("/"), "emails are not sent")

    def test_pilot_banner_asks_for_fictional_students(self):
        with self.settings(OSEA_ENVIRONMENT_LABEL="Pilot", EMAIL_BACKEND="core.mail.SafeSMTPBackend"):
            response = self.client.get("/")
        self.assertContains(response, "Pilot site · use fictional student information only")
        self.assertNotContains(response, "emails are not sent")


class EndPilotTests(TransactionTestCase):
    def setUp(self):
        from audit.log import record

        self.admin = User.objects.create_user(email="admin@example.org", password=PASSWORD, role=User.Role.ADMIN)
        record(self.admin, "test.event", "Pilot activity")

    def test_refuses_on_the_live_site(self):
        with self.settings(OSEA_ENVIRONMENT_LABEL=""):
            with self.assertRaises(CommandError):
                call_command("end_pilot", confirm="DELETE PILOT DATA")
        self.assertTrue(User.objects.exists())

    def test_needs_the_exact_phrase(self):
        with self.settings(OSEA_ENVIRONMENT_LABEL="Pilot"):
            with self.assertRaises(CommandError):
                call_command("end_pilot", confirm="yes")
        self.assertTrue(User.objects.exists())

    def test_deletes_everything_including_the_activity_log(self):
        from audit.models import AuditEvent

        with self.settings(OSEA_ENVIRONMENT_LABEL="Pilot"):
            call_command("end_pilot", confirm="DELETE PILOT DATA", stdout=StringIO())
        self.assertFalse(User.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())
