import datetime
import time
from unittest import mock

from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts import verification
from accounts.models import User
from audit.log import record
from audit.models import AuditEvent

from . import services
from .manage_views import schools_needing_membership_attention
from .models import CoachAccess, Membership, School, SchoolBoard, SchoolYear
from .permissions import schools_for

PASSWORD = "a-long-test-password"


class FakeRequest:
    """Enough of a request for the services to build links in emails."""

    def build_absolute_uri(self, path):
        return "https://osea.example" + path


def make_user(email, role=User.Role.COACH, verified=True, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        first_name=email.split("@")[0].title(),
        last_name="Test",
        role=role,
        email_verified_at=timezone.now() if verified else None,
        **extra,
    )


class SchoolTestData(TestCase):
    """Two schools; one approved coach at A, one pending coach at B."""

    @classmethod
    def setUpTestData(cls):
        cls.board = SchoolBoard.objects.create(name="Test Board", email_domains="tb.example.ca")
        cls.school_a = School.objects.create(
            name="School A", city="Townville", board=cls.board, level=School.Level.SECONDARY, admin_notes="SECRET-NOTE"
        )
        cls.school_b = School.objects.create(
            name="School B", city="Townville", board=cls.board, level=School.Level.ELEMENTARY
        )
        cls.year = SchoolYear.objects.create(
            name="2026–27", start_date=datetime.date(2026, 9, 1), end_date=datetime.date(2027, 6, 30), is_current=True
        )
        cls.admin = make_user("admin@example.org", role=User.Role.ADMIN)
        cls.coach = make_user("coach@tb.example.ca")
        cls.access_a = CoachAccess.objects.create(
            coach=cls.coach, school=cls.school_a, position="Teacher", status=CoachAccess.Status.APPROVED
        )
        cls.pending_coach = make_user("pending@tb.example.ca")
        cls.access_b = CoachAccess.objects.create(coach=cls.pending_coach, school=cls.school_b, position="Teacher")


# ---------------------------------------------------------------- permissions


class SchoolPermissionTests(SchoolTestData):
    def test_admin_can_see_every_school(self):
        self.assertEqual(set(schools_for(self.admin)), {self.school_a, self.school_b})

    def test_approved_coach_sees_only_their_school(self):
        self.assertEqual(list(schools_for(self.coach)), [self.school_a])

    def test_pending_declined_and_removed_access_give_nothing(self):
        for status in [CoachAccess.Status.PENDING, CoachAccess.Status.DECLINED, CoachAccess.Status.REVOKED]:
            with self.subTest(status=status):
                CoachAccess.objects.filter(pk=self.access_b.pk).update(status=status)
                self.assertFalse(schools_for(self.pending_coach).exists())

    def test_turned_off_coach_or_inactive_school_gives_nothing(self):
        self.coach.is_active = False
        self.coach.save()
        self.assertFalse(schools_for(self.coach).exists())
        self.coach.is_active = True
        self.coach.save()
        self.school_a.is_active = False
        self.school_a.save()
        self.assertFalse(schools_for(self.coach).exists())

    def test_coach_school_page_is_blocked_on_the_server_for_other_schools(self):
        self.client.force_login(self.coach)
        self.assertEqual(self.client.get(reverse("schools:my_school", args=[self.school_a.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("schools:my_school", args=[self.school_b.pk])).status_code, 403)

    def test_pending_coach_cannot_open_the_school_they_asked_for(self):
        self.client.force_login(self.pending_coach)
        self.assertEqual(self.client.get(reverse("schools:my_school", args=[self.school_b.pk])).status_code, 403)

    def test_coach_school_page_never_shows_osea_private_notes(self):
        self.client.force_login(self.coach)
        response = self.client.get(reverse("schools:my_school", args=[self.school_a.pk]))
        self.assertNotContains(response, "SECRET-NOTE")

    def test_every_admin_page_refuses_coaches_and_signed_out_visitors(self):
        a, s, y = self.access_b.pk, self.school_a.pk, self.year.pk
        pages = [
            ("get", reverse("schools:access_requests")),
            ("get", reverse("schools:access_request", args=[a])),
            ("post", reverse("schools:access_request", args=[a])),
            ("post", reverse("schools:access_revoke", args=[self.access_a.pk])),
            ("get", reverse("schools:coach_list")),
            ("get", reverse("schools:coach_detail", args=[self.coach.pk])),
            ("post", reverse("schools:coach_set_active", args=[self.coach.pk])),
            ("get", reverse("schools:school_list")),
            ("get", reverse("schools:school_create")),
            ("get", reverse("schools:school_detail", args=[s])),
            ("get", reverse("schools:school_edit", args=[s])),
            ("post", reverse("schools:membership_edit", args=[s, y])),
            ("get", reverse("schools:board_list")),
            ("get", reverse("schools:board_create")),
            ("get", reverse("schools:year_list")),
            ("post", reverse("schools:year_create")),
            ("get", reverse("schools:exports")),
            ("get", reverse("schools:export_csv", args=["coaches"])),
            ("get", reverse("audit:activity_log")),
        ]
        for method, url in pages:
            with self.subTest(url=url, who="signed out"):
                self.client.logout()
                response = getattr(self.client, method)(url, {"action": "approve", "active": "0"})
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("accounts:login"), response.url)
            with self.subTest(url=url, who="coach"):
                self.client.force_login(self.coach)
                response = getattr(self.client, method)(url, {"action": "approve", "active": "0"})
                self.assertEqual(response.status_code, 403)
        # And nothing changed as a result of those attempts.
        self.access_b.refresh_from_db()
        self.coach.refresh_from_db()
        self.assertEqual(self.access_b.status, CoachAccess.Status.PENDING)
        self.assertTrue(self.coach.is_active)
        self.assertFalse(AuditEvent.objects.exists())

    def test_admin_can_open_every_admin_page(self):
        self.client.force_login(self.admin)
        for url in [
            reverse("core:admin_dashboard"),
            reverse("schools:access_requests"),
            reverse("schools:access_requests") + "?show=decided",
            reverse("schools:access_request", args=[self.access_b.pk]),
            reverse("schools:coach_list") + "?q=coach",
            reverse("schools:coach_detail", args=[self.coach.pk]),
            reverse("schools:school_list") + "?membership=none&level=secondary",
            reverse("schools:school_detail", args=[self.school_a.pk]),
            reverse("schools:school_edit", args=[self.school_a.pk]),
            reverse("schools:membership_edit", args=[self.school_a.pk, self.year.pk]),
            reverse("schools:board_list"),
            reverse("schools:year_list"),
            reverse("schools:exports"),
            reverse("audit:activity_log") + "?area=access",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


# ---------------------------------------------------------------- sign-up


class SignUpTests(SchoolTestData):
    url = reverse("accounts:sign_up")

    def form_data(self, **overrides):
        data = {
            "account-first_name": "New",
            "account-last_name": "Coach",
            "account-email": "New.Coach@tb.example.ca",
            "account-password1": PASSWORD,
            "account-password2": PASSWORD,
            "school-school": self.school_b.pk,
            "school-requested_school_name": "",
            "school-position": "Teacher",
            "school-attestation": "on",
        }
        data.update(overrides)
        return data

    def test_sign_up_creates_an_unverified_coach_with_a_pending_request(self):
        response = self.client.post(self.url, self.form_data())
        self.assertRedirects(response, reverse("core:dashboard"), fetch_redirect_response=False)
        user = User.objects.get(email="new.coach@tb.example.ca")
        self.assertEqual(user.role, User.Role.COACH)
        self.assertIsNone(user.email_verified_at)
        access = user.school_access.get()
        self.assertEqual((access.school, access.status), (self.school_b, CoachAccess.Status.PENDING))
        self.assertFalse(schools_for(user).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/account/verify/", mail.outbox[0].body)
        self.assertEqual(
            set(AuditEvent.objects.values_list("action", flat=True)), {"coach.signed_up", "access.requested"}
        )

    def test_sign_up_cannot_be_used_to_become_an_administrator(self):
        self.client.post(self.url, self.form_data(**{"account-role": "admin", "role": "admin", "is_staff": "on"}))
        user = User.objects.get(email="new.coach@tb.example.ca")
        self.assertEqual(user.role, User.Role.COACH)
        self.assertFalse(user.is_staff)

    def test_unlisted_school_is_recorded_for_an_admin_to_add(self):
        self.client.post(self.url, self.form_data(**{"school-school": "", "school-requested_school_name": "New PS"}))
        access = CoachAccess.objects.get(coach__email="new.coach@tb.example.ca")
        self.assertIsNone(access.school)
        self.assertEqual(access.requested_school_name, "New PS")

    def test_must_choose_exactly_one_school(self):
        for overrides in [
            {"school-school": "", "school-requested_school_name": ""},
            {"school-requested_school_name": "Also this one"},
        ]:
            with self.subTest(overrides=overrides):
                response = self.client.post(self.url, self.form_data(**overrides))
                self.assertEqual(response.status_code, 200)
                self.assertFalse(User.objects.filter(email="new.coach@tb.example.ca").exists())

    def test_attestation_and_matching_passwords_are_required(self):
        for overrides in [{"school-attestation": ""}, {"account-password2": "something-else-entirely"}]:
            with self.subTest(overrides=overrides):
                response = self.client.post(self.url, self.form_data(**overrides))
                self.assertEqual(response.status_code, 200)
                self.assertFalse(User.objects.filter(email="new.coach@tb.example.ca").exists())

    def test_existing_email_is_refused_in_any_letter_case(self):
        response = self.client.post(self.url, self.form_data(**{"account-email": "COACH@tb.example.ca"}))
        self.assertContains(response, "already exists")
        self.assertEqual(User.objects.filter(email__iexact="coach@tb.example.ca").count(), 1)


class EmailVerificationTests(SchoolTestData):
    def test_link_confirms_the_address(self):
        token = verification.make_token(self.pending_coach)
        self.pending_coach.email_verified_at = None
        self.pending_coach.save()
        self.client.get(reverse("accounts:verify_email", args=[token]))
        self.pending_coach.refresh_from_db()
        self.assertIsNotNone(self.pending_coach.email_verified_at)

    def test_tampered_link_is_refused(self):
        token = verification.make_token(self.pending_coach)
        response = self.client.get(reverse("accounts:verify_email", args=[token[:-2] + "xx"]))
        self.assertEqual(response.status_code, 400)

    def test_link_expires_after_three_days(self):
        token = verification.make_token(self.pending_coach)
        later = time.time() + verification.MAX_AGE_SECONDS + 60
        with mock.patch("django.core.signing.time.time", return_value=later):
            self.assertIsNone(verification.user_from_token(token))

    def test_link_stops_working_if_the_email_changes(self):
        token = verification.make_token(self.pending_coach)
        self.pending_coach.email = "changed@tb.example.ca"
        self.pending_coach.save()
        self.assertIsNone(verification.user_from_token(token))


class RequestAnotherSchoolTests(SchoolTestData):
    def test_coach_can_ask_for_another_school_once(self):
        self.client.force_login(self.coach)
        url = reverse("schools:request_school")
        data = {"school": self.school_b.pk, "position": "Teacher", "attestation": "on"}
        self.client.post(url, data)
        self.assertEqual(self.coach.school_access.get(school=self.school_b).status, CoachAccess.Status.PENDING)
        response = self.client.post(url, data)
        self.assertContains(response, "already have a request")
        self.assertEqual(self.coach.school_access.filter(school=self.school_b).count(), 1)


# ---------------------------------------------------------------- approval rules


class AccessDecisionTests(SchoolTestData):
    def test_cannot_approve_until_email_is_confirmed(self):
        self.pending_coach.email_verified_at = None
        self.pending_coach.save()
        with self.assertRaises(ValidationError):
            services.approve(FakeRequest(), self.access_b, self.admin)
        self.access_b.refresh_from_db()
        self.assertEqual(self.access_b.status, CoachAccess.Status.PENDING)

    def test_approval_grants_access_logs_who_did_it_and_emails_the_coach(self):
        with self.captureOnCommitCallbacks(execute=True):
            services.approve(FakeRequest(), self.access_b, self.admin, note="Welcome!")
        self.access_b.refresh_from_db()
        self.assertEqual(self.access_b.status, CoachAccess.Status.APPROVED)
        self.assertEqual(self.access_b.decided_by, self.admin)
        self.assertEqual(list(schools_for(self.pending_coach)), [self.school_b])
        event = AuditEvent.objects.get(action="access.approved")
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(mail.outbox[-1].to, [self.pending_coach.email])
        self.assertIn("Welcome!", mail.outbox[-1].body)

    def test_unlisted_school_must_be_linked_before_approval(self):
        access = CoachAccess.objects.create(
            coach=make_user("new@tb.example.ca"), requested_school_name="Somewhere PS", position="Teacher"
        )
        with self.assertRaises(ValidationError):
            services.approve(FakeRequest(), access, self.admin)
        services.approve(FakeRequest(), access, self.admin, school=self.school_b)
        access.refresh_from_db()
        self.assertEqual((access.school, access.status), (self.school_b, CoachAccess.Status.APPROVED))

    def test_declining_needs_a_reason_and_gives_no_access(self):
        with self.assertRaises(ValidationError):
            services.decline(FakeRequest(), self.access_b, self.admin, note="  ")
        with self.captureOnCommitCallbacks(execute=True):
            services.decline(FakeRequest(), self.access_b, self.admin, note="Not on staff list.")
        self.access_b.refresh_from_db()
        self.assertEqual(self.access_b.status, CoachAccess.Status.DECLINED)
        self.assertFalse(schools_for(self.pending_coach).exists())
        self.assertIn("Not on staff list.", mail.outbox[-1].body)

    def test_removing_access_takes_effect_immediately(self):
        self.client.force_login(self.coach)
        page = reverse("schools:my_school", args=[self.school_a.pk])
        self.assertEqual(self.client.get(page).status_code, 200)
        services.revoke(FakeRequest(), self.access_a, self.admin, note="Left the school.")
        self.assertEqual(self.client.get(page).status_code, 403)

    def test_admin_can_approve_through_the_review_page(self):
        self.client.force_login(self.admin)
        url = reverse("schools:access_request", args=[self.access_b.pk])
        response = self.client.post(url, {"action": "approve", "decision_note": ""})
        self.assertRedirects(response, reverse("schools:access_requests"))
        self.access_b.refresh_from_db()
        self.assertEqual(self.access_b.status, CoachAccess.Status.APPROVED)

    def test_review_flags_email_from_outside_the_board(self):
        outsider = make_user("someone@mail.example.com")
        access = CoachAccess.objects.create(coach=outsider, school=self.school_a, position="Volunteer")
        self.assertTrue(any("not from Test Board" in str(flag) for flag in access.review_flags()))
        self.assertEqual(self.access_b.review_flags(), [])


# ---------------------------------------------------------------- memberships and school years


class MembershipTests(SchoolTestData):
    def membership_url(self):
        return reverse("schools:membership_edit", args=[self.school_a.pk, self.year.pk])

    def test_exception_requires_an_explanation(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.membership_url(), {"status": "exempt", "notes": ""})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Membership.objects.exists())
        self.client.post(self.membership_url(), {"status": "exempt", "notes": "Pilot school"})
        self.assertEqual(Membership.objects.get().status, Membership.Status.EXEMPT)

    def test_changes_are_logged_with_before_and_after_values(self):
        self.client.force_login(self.admin)
        self.client.post(self.membership_url(), {"status": "pending"})
        self.client.post(self.membership_url(), {"status": "confirmed", "amount": "150", "paid_on": "2026-10-01"})
        membership = Membership.objects.get()
        self.assertEqual(membership.updated_by, self.admin)
        event = AuditEvent.objects.filter(action="membership.updated").get()
        self.assertEqual(event.changes["status"], ["Pending", "Confirmed"])
        self.assertEqual(event.changes["amount"], ["", "150.00"])

    def test_dashboard_lists_schools_with_coaches_but_no_confirmed_membership(self):
        # A has an approved coach and no record; B has a pending coach and a pending membership.
        Membership.objects.create(school=self.school_b, school_year=self.year)
        School.objects.create(name="No Coaches", city="X", level=School.Level.SECONDARY)
        self.assertEqual(set(schools_needing_membership_attention(self.year)), {self.school_a, self.school_b})
        Membership.objects.create(school=self.school_a, school_year=self.year, status=Membership.Status.CONFIRMED)
        Membership.objects.filter(school=self.school_b).update(status=Membership.Status.EXEMPT, notes="ok")
        self.assertFalse(schools_needing_membership_attention(self.year).exists())

    def test_marking_a_year_current_unmarks_the_previous_one(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("schools:year_create"),
            {"name": "2027–28", "start_date": "2027-09-01", "end_date": "2028-06-30", "make_current": "on"},
        )
        self.assertEqual(SchoolYear.current().name, "2027–28")
        self.assertEqual(SchoolYear.objects.filter(is_current=True).count(), 1)


# ---------------------------------------------------------------- accounts, log and exports


class CoachAccountTests(SchoolTestData):
    def test_turning_off_a_coach_blocks_sign_in_and_is_logged(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("schools:coach_set_active", args=[self.coach.pk]), {"active": "0"})
        self.client.logout()
        self.assertFalse(self.client.login(email=self.coach.email, password=PASSWORD))
        self.assertTrue(AuditEvent.objects.filter(action="coach.deactivated", actor=self.admin).exists())


class AuditLogTests(SchoolTestData):
    def test_entries_cannot_be_changed_or_deleted(self):
        event = record(self.admin, "test.action", "Something happened")
        event.summary = "Something else"
        with self.assertRaises(PermissionDenied):
            event.save()
        with self.assertRaises(PermissionDenied):
            event.delete()
        self.assertEqual(AuditEvent.objects.get().summary, "Something happened")

    def test_database_blocks_bulk_changes_too(self):
        record(self.admin, "test.action", "Something happened")
        for attempt in [
            lambda: AuditEvent.objects.update(summary="Rewritten"),
            lambda: AuditEvent.objects.all().delete(),
        ]:
            with self.subTest(), self.assertRaises(DatabaseError), transaction.atomic():
                attempt()
        self.assertEqual(AuditEvent.objects.get().summary, "Something happened")


class ExportTests(SchoolTestData):
    def test_csv_export_is_logged_and_neutralises_spreadsheet_formulas(self):
        School.objects.create(name='=HYPERLINK("http://bad.example")', city="X", level=School.Level.SECONDARY)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("schools:export_csv", args=["schools"]))
        body = response.content.decode("utf-8-sig")
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("School,City,Board", body)
        self.assertIn("'=HYPERLINK", body)
        self.assertTrue(AuditEvent.objects.filter(action="export.downloaded", actor=self.admin).exists())

    def test_coach_export_includes_each_access_record(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("schools:export_csv", args=["coaches"])).content.decode("utf-8-sig")
        self.assertIn("coach@tb.example.ca", body)
        self.assertIn("pending@tb.example.ca", body)
