from django.test import TestCase
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
