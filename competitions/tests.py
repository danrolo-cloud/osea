import datetime

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from schools.models import CoachAccess, Membership, School, SchoolYear, Student

from . import services
from .models import Competition, Division, Game, Registration, RosterChange

PASSWORD = "a-long-test-password"
NOW = timezone.now()


class FakeRequest:
    def build_absolute_uri(self, path):
        return "https://osea.example" + path


REQ = FakeRequest()


def user(email, role=User.Role.COACH):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        first_name=email[:5].title(),
        last_name="T",
        role=role,
        email_verified_at=NOW,
    )


class CompetitionTestData(TestCase):
    """
    A published Valorant-style competition with registration open now:
    secondary schools only, grades 9-12, 5 players per match, rosters of 5-7,
    at most 2 teams per school. School A's membership is confirmed; B's is pending.
    """

    @classmethod
    def setUpTestData(cls):
        cls.year = SchoolYear.objects.create(
            name="2026–27", start_date=datetime.date(2026, 9, 1), end_date=datetime.date(2027, 6, 30), is_current=True
        )
        cls.school_a = School.objects.create(name="School A", city="X", level=School.Level.SECONDARY)
        cls.school_b = School.objects.create(name="School B", city="X", level=School.Level.SECONDARY)
        cls.elementary = School.objects.create(name="Elem", city="X", level=School.Level.ELEMENTARY)
        Membership.objects.create(school=cls.school_a, school_year=cls.year, status=Membership.Status.CONFIRMED)
        Membership.objects.create(school=cls.school_b, school_year=cls.year, status=Membership.Status.PENDING)

        cls.admin = user("admin@example.org", User.Role.ADMIN)
        cls.coach_a = user("coach.a@example.org")
        cls.coach_b = user("coach.b@example.org")
        for coach, school in [(cls.coach_a, cls.school_a), (cls.coach_b, cls.school_b), (cls.coach_a, cls.elementary)]:
            CoachAccess.objects.create(coach=coach, school=school, position="T", status=CoachAccess.Status.APPROVED)

        cls.game = Game.objects.create(name="Valorant", gamer_tag_label="Riot ID", rank_label="Rank")
        cls.comp = Competition.objects.create(
            school_year=cls.year,
            game=cls.game,
            name="Valorant Winter League",
            registration_opens_at=NOW - datetime.timedelta(days=1),
            registration_closes_at=NOW + datetime.timedelta(days=7),
            roster_deadline=NOW + datetime.timedelta(days=14),
            allowed_levels=[School.Level.SECONDARY],
            min_grade=9,
            max_grade=12,
            players_per_team=5,
            roster_min=5,
            roster_max=7,
            max_teams_per_school=2,
            require_gamer_tag=True,
            rank_requirement=Competition.RankRequirement.OPTIONAL,
            is_published=True,
        )
        cls.division = Division.objects.create(competition=cls.comp, name="Platinum–Diamond")
        cls.students_a = [
            Student.objects.create(school=cls.school_a, first_name=f"Ana{i}", last_initial="Z", grade=9 + i % 4)
            for i in range(10)
        ]
        cls.grade8 = Student.objects.create(school=cls.school_a, first_name="Young", last_initial="Y", grade=8)
        cls.students_b = [
            Student.objects.create(school=cls.school_b, first_name=f"Ben{i}", last_initial="Q", grade=10)
            for i in range(6)
        ]

    def register(self, coach=None, school=None, name="Team One", competition=None):
        return services.create_registration(
            coach or self.coach_a, competition or self.comp, school or self.school_a, name
        )

    def fill(self, registration, students, coach=None):
        for i, student in enumerate(students):
            services.add_player(registration, coach or self.coach_a, student, gamer_tag=f"Player{i}#NA1")

    def submitted(self, coach=None, school=None, students=None, name="Team One"):
        registration = self.register(coach, school, name)
        self.fill(registration, students or self.students_a[:5], coach)
        return services.submit(REQ, registration, coach or self.coach_a, consent_confirmed=True)

    def set_dates(self, opens, closes, deadline):
        Competition.objects.filter(pk=self.comp.pk).update(
            registration_opens_at=NOW + datetime.timedelta(days=opens),
            registration_closes_at=NOW + datetime.timedelta(days=closes),
            roster_deadline=NOW + datetime.timedelta(days=deadline),
        )
        self.comp.refresh_from_db()


# ------------------------------------------------------------------ competition settings


class CompetitionSettingsTests(CompetitionTestData):
    def post_settings(self, **overrides):
        data = {
            "name": "Test League",
            "game": self.game.pk,
            "school_year": self.year.pk,
            "format": "league",
            "registration_opens_at": "2027-01-05T09:00",
            "registration_closes_at": "2027-01-20T23:59",
            "roster_deadline": "2027-02-01T23:59",
            "allowed_levels": ["secondary"],
            "min_grade": 9,
            "max_grade": 12,
            "players_per_team": 5,
            "roster_min": 5,
            "roster_max": 7,
            "rank_requirement": "off",
        }
        data.update(overrides)
        self.client.force_login(self.admin)
        return self.client.post(reverse("competitions:competition_create"), data)

    def test_admin_sets_every_rule_and_times_are_toronto_time(self):
        response = self.post_settings()
        competition = Competition.objects.get(name="Test League")
        self.assertRedirects(response, reverse("competitions:manage_competition", args=[competition.pk]))
        self.assertEqual(competition.allowed_levels, ["secondary"])
        self.assertEqual((competition.roster_min, competition.roster_max), (5, 7))
        # 9:00 in Toronto in January (EST, UTC-5) is 14:00 UTC.
        self.assertEqual(competition.registration_opens_at.astimezone(datetime.UTC).hour, 14)
        self.assertTrue(AuditEvent.objects.filter(action="competition.created", actor=self.admin).exists())

    def test_inconsistent_settings_are_refused_with_clear_messages(self):
        cases = [
            ({"roster_min": 8}, "be smaller than the minimum"),
            ({"roster_min": 3, "roster_max": 4}, "at least the number of players in a match"),
            ({"min_grade": 12, "max_grade": 9}, "be lower than the lowest grade"),
            ({"registration_closes_at": "2027-01-01T09:00"}, "must close after it opens"),
            ({"roster_deadline": "2027-01-10T09:00"}, "be before registration closes"),
            ({"allowed_levels": []}, "This field is required"),
        ]
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                response = self.post_settings(**overrides)
                self.assertContains(response, message)
        self.assertFalse(Competition.objects.filter(name="Test League").exists())

    def test_daylight_saving_is_handled(self):
        # 9:00 in Toronto in May (EDT, UTC-4) is 13:00 UTC.
        self.post_settings(
            registration_opens_at="2027-05-03T09:00",
            registration_closes_at="2027-05-20T09:00",
            roster_deadline="2027-05-30T09:00",
        )
        competition = Competition.objects.get(name="Test League")
        self.assertEqual(competition.registration_opens_at.astimezone(datetime.UTC).hour, 13)


# ------------------------------------------------------------------ registration rules


class StartRegistrationTests(CompetitionTestData):
    def test_coach_can_start_a_draft(self):
        registration = self.register()
        self.assertEqual(registration.status, Registration.Status.DRAFT)
        self.assertTrue(AuditEvent.objects.filter(action="registration.created", actor=self.coach_a).exists())

    def test_registration_window_is_enforced(self):
        for opens, closes in [(1, 5), (-10, -1)]:  # not open yet; already closed
            with self.subTest(opens=opens, closes=closes):
                self.set_dates(opens, closes, closes + 7)
                with self.assertRaises(ValidationError):
                    self.register()

    def test_unpublished_competitions_take_no_registrations(self):
        Competition.objects.filter(pk=self.comp.pk).update(is_published=False)
        self.comp.refresh_from_db()
        with self.assertRaises(ValidationError):
            self.register()

    def test_coach_cannot_register_a_school_they_are_not_approved_for(self):
        with self.assertRaisesMessage(ValidationError, "don't have access"):
            self.register(coach=self.coach_b, school=self.school_a)

    def test_school_level_eligibility(self):
        with self.assertRaisesMessage(ValidationError, "secondary schools"):
            self.register(school=self.elementary)

    def test_teams_per_school_limit(self):
        self.register(name="One")
        self.register(name="Two")
        with self.assertRaisesMessage(ValidationError, "at most 2 team"):
            self.register(name="Three")

    def test_team_names_are_unique_in_a_competition_ignoring_case(self):
        self.register(name="Lynx")
        with self.assertRaisesMessage(ValidationError, "already called"):
            self.register(coach=self.coach_b, school=self.school_b, name="LYNX")


class RosterRuleTests(CompetitionTestData):
    def test_grade_outside_the_competition_range_is_refused(self):
        registration = self.register()
        with self.assertRaisesMessage(ValidationError, "grade 8"):
            services.add_player(registration, self.coach_a, self.grade8, gamer_tag="Kid#1")

    def test_student_from_another_school_is_refused(self):
        registration = self.register()
        with self.assertRaisesMessage(ValidationError, "not a student at this school"):
            services.add_player(registration, self.coach_a, self.students_b[0], gamer_tag="B#1")

    def test_required_in_game_name_uses_the_game_label(self):
        registration = self.register()
        with self.assertRaisesMessage(ValidationError, "Riot ID is required"):
            services.add_player(registration, self.coach_a, self.students_a[0], gamer_tag="  ")

    def test_roster_maximum(self):
        registration = self.register()
        self.fill(registration, self.students_a[:7])
        with self.assertRaisesMessage(ValidationError, "roster is full"):
            services.add_player(registration, self.coach_a, self.students_a[7], gamer_tag="x")

    def test_a_student_can_only_play_for_one_team_per_competition(self):
        first = self.register(name="One")
        second = self.register(name="Two")
        services.add_player(first, self.coach_a, self.students_a[0], gamer_tag="x")
        with self.assertRaisesMessage(ValidationError, "already on another team"):
            services.add_player(second, self.coach_a, self.students_a[0], gamer_tag="x")
        services.withdraw(REQ, first, self.coach_a)
        services.add_player(second, self.coach_a, self.students_a[0], gamer_tag="x")  # free again

    def test_other_coaches_cannot_change_a_roster(self):
        registration = self.register()
        with self.assertRaisesMessage(ValidationError, "don't have access"):
            services.add_player(registration, self.coach_b, self.students_a[0], gamer_tag="x")


class SubmitTests(CompetitionTestData):
    def test_consent_is_required_and_recorded(self):
        registration = self.register()
        self.fill(registration, self.students_a[:5])
        with self.assertRaisesMessage(ValidationError, "consent forms"):
            services.submit(REQ, registration, self.coach_a, consent_confirmed=False)
        services.submit(REQ, registration, self.coach_a, consent_confirmed=True)
        registration.refresh_from_db()
        self.assertEqual(registration.status, Registration.Status.SUBMITTED)
        self.assertEqual(registration.consent_confirmed_by, self.coach_a)
        self.assertIsNotNone(registration.consent_confirmed_at)

    def test_roster_must_meet_the_minimum(self):
        registration = self.register()
        self.fill(registration, self.students_a[:4])
        with self.assertRaisesMessage(ValidationError, "at least 5 are needed"):
            services.submit(REQ, registration, self.coach_a, consent_confirmed=True)

    def test_submitted_rosters_are_locked_until_reopened(self):
        registration = self.submitted()
        with self.assertRaises(ValidationError):
            services.add_player(registration, self.coach_a, self.students_a[6], gamer_tag="x")
        services.unsubmit(registration, self.coach_a)
        services.add_player(registration, self.coach_a, self.students_a[6], gamer_tag="x")

    def test_drafts_lock_when_registration_closes(self):
        registration = self.register()
        self.set_dates(-10, -1, 7)
        registration.refresh_from_db()
        self.assertFalse(services.coach_can_edit(registration))
        with self.assertRaises(ValidationError):
            services.add_player(registration, self.coach_a, self.students_a[0], gamer_tag="x")

    def test_requested_changes_can_be_made_after_closing_until_the_roster_deadline(self):
        registration = self.submitted()
        services.request_changes(REQ, registration, self.admin, "Please add a sixth player.")
        self.set_dates(-10, -1, 7)
        registration.refresh_from_db()
        services.add_player(registration, self.coach_a, self.students_a[5], gamer_tag="x")
        services.submit(REQ, registration, self.coach_a, consent_confirmed=True)
        registration.refresh_from_db()
        self.assertEqual(registration.status, Registration.Status.SUBMITTED)
        self.set_dates(-20, -10, -1)
        services.request_changes(REQ, registration, self.admin, "One more thing.")
        registration.refresh_from_db()
        self.assertFalse(services.coach_can_edit(registration))


class ApprovalTests(CompetitionTestData):
    def test_approval_requires_confirmed_membership(self):
        registration = self.submitted(coach=self.coach_b, school=self.school_b, students=self.students_b[:5])
        with self.assertRaisesMessage(ValidationError, "membership isn't confirmed"):
            services.approve(REQ, registration, self.admin)
        Membership.objects.filter(school=self.school_b).update(status=Membership.Status.EXEMPT, notes="ok")
        services.approve(REQ, registration, self.admin)

    def test_approval_emails_coaches_logs_the_admin_and_never_auto_places(self):
        registration = self.submitted()
        with self.captureOnCommitCallbacks(execute=True):
            services.approve(REQ, registration, self.admin, message="Good luck!")
        registration.refresh_from_db()
        self.assertEqual(registration.status, Registration.Status.APPROVED)
        self.assertIsNone(registration.division)  # placement is always an admin decision
        self.assertEqual(AuditEvent.objects.get(action="registration.approved").actor, self.admin)
        self.assertEqual(mail.outbox[-1].to, ["coach.a@example.org"])
        self.assertIn("Good luck!", mail.outbox[-1].body)

    def test_competition_capacity(self):
        Competition.objects.filter(pk=self.comp.pk).update(max_teams=1)
        first = self.submitted(name="One")
        second = self.submitted(name="Two", students=self.students_a[5:10])
        services.approve(REQ, first, self.admin)
        with self.assertRaisesMessage(ValidationError, "competition is full"):
            services.approve(REQ, second, self.admin)
        services.waitlist(REQ, second, self.admin)
        second.refresh_from_db()
        self.assertEqual(second.status, Registration.Status.WAITLISTED)

    def test_division_must_belong_to_the_competition(self):
        other = Competition.objects.create(
            school_year=self.year,
            game=self.game,
            name="Other",
            registration_opens_at=NOW,
            registration_closes_at=NOW + datetime.timedelta(days=1),
            roster_deadline=NOW + datetime.timedelta(days=2),
            allowed_levels=["secondary"],
            min_grade=9,
            max_grade=12,
            players_per_team=1,
            roster_min=1,
            roster_max=1,
        )
        foreign = Division.objects.create(competition=other, name="Elsewhere")
        registration = self.submitted()
        with self.assertRaises(ValidationError):
            services.approve(REQ, registration, self.admin, division=foreign)
        services.approve(REQ, registration, self.admin, division=self.division)
        registration.refresh_from_db()
        self.assertEqual(registration.division, self.division)

    def test_asking_for_changes_needs_a_message(self):
        registration = self.submitted()
        with self.assertRaises(ValidationError):
            services.request_changes(REQ, registration, self.admin, "   ")

    def test_admin_withdrawal_needs_a_reason(self):
        registration = self.submitted()
        with self.assertRaises(ValidationError):
            services.withdraw(REQ, registration, self.admin, reason="", by_admin=True)
        services.withdraw(REQ, registration, self.admin, reason="School request", by_admin=True)


class RosterChangeTests(CompetitionTestData):
    def approved(self):
        registration = self.submitted()
        return services.approve(REQ, registration, self.admin)

    def test_changes_only_for_approved_teams_before_the_deadline(self):
        registration = self.submitted()
        with self.assertRaises(ValidationError):
            services.request_roster_change(registration, self.coach_a, player_in=self.students_a[6], reason="r")
        registration = services.approve(REQ, registration, self.admin)
        self.set_dates(-20, -10, -1)
        registration.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "before the roster deadline"):
            services.request_roster_change(
                registration, self.coach_a, player_in=self.students_a[6], gamer_tag="x", reason="r"
            )

    def test_swap_works_even_when_the_roster_is_at_its_exact_size(self):
        Competition.objects.filter(pk=self.comp.pk).update(roster_max=5)
        registration = self.approved()
        out, new = self.students_a[0], self.students_a[6]
        change = services.request_roster_change(
            registration, self.coach_a, player_out=out, player_in=new, gamer_tag="New#1", reason="Moved away"
        )
        services.approve_roster_change(REQ, change, self.admin)
        names = set(registration.roster.values_list("student__first_name", flat=True))
        self.assertIn(new.first_name, names)
        self.assertNotIn(out.first_name, names)
        self.assertEqual(len(names), 5)

    def test_change_that_breaks_roster_limits_is_refused_at_approval(self):
        registration = self.approved()  # 5 players, min 5
        change = services.request_roster_change(registration, self.coach_a, player_out=self.students_a[0], reason="r")
        with self.assertRaisesMessage(ValidationError, "at least 5 are needed"):
            services.approve_roster_change(REQ, change, self.admin)
        self.assertEqual(registration.roster.count(), 5)

    def test_ineligible_incoming_player_is_refused_when_requested(self):
        registration = self.approved()
        with self.assertRaisesMessage(ValidationError, "grade 8"):
            services.request_roster_change(registration, self.coach_a, player_in=self.grade8, gamer_tag="x", reason="r")

    def test_declining_needs_a_message(self):
        registration = self.approved()
        change = services.request_roster_change(
            registration, self.coach_a, player_in=self.students_a[6], gamer_tag="x", reason="r"
        )
        with self.assertRaises(ValidationError):
            services.decline_roster_change(REQ, change, self.admin, note="")
        services.decline_roster_change(REQ, change, self.admin, note="Not eligible this season")
        change.refresh_from_db()
        self.assertEqual(change.status, RosterChange.Status.DECLINED)


# ------------------------------------------------------------------ permissions and privacy


class PermissionTests(CompetitionTestData):
    def test_coaches_cannot_see_or_change_another_schools_registration(self):
        registration = self.register()
        self.fill(registration, self.students_a[:5])
        entry = registration.roster.first()
        self.client.force_login(self.coach_b)
        pk = registration.pk
        self.assertEqual(self.client.get(reverse("competitions:registration", args=[pk])).status_code, 403)
        for name, args, data in [
            (
                "competitions:add_player",
                [pk],
                {"first_name": "Evil", "last_initial": "E", "grade": 10, "gamer_tag": "x"},
            ),
            ("competitions:remove_player", [pk, entry.pk], {}),
            ("competitions:rename", [pk], {"team_name": "Hacked"}),
            ("competitions:submit", [pk], {"consent": "on"}),
            ("competitions:withdraw", [pk], {}),
            ("competitions:request_change", [pk], {"reason": "x"}),
        ]:
            with self.subTest(url=name):
                self.assertEqual(self.client.post(reverse(name, args=args), data).status_code, 403)
        registration.refresh_from_db()
        self.assertEqual((registration.team_name, registration.status), ("Team One", Registration.Status.DRAFT))
        self.assertEqual(registration.roster.count(), 5)
        self.assertFalse(Student.objects.filter(first_name="Evil").exists())

    def test_student_lists_are_private_to_the_school(self):
        self.client.force_login(self.coach_b)
        self.assertEqual(
            self.client.get(reverse("competitions:student_list", args=[self.school_a.pk])).status_code, 403
        )
        self.assertEqual(
            self.client.get(reverse("competitions:student_list", args=[self.school_b.pk])).status_code, 200
        )

    def test_admin_competition_pages_refuse_coaches(self):
        registration = self.register()
        self.client.force_login(self.coach_a)
        for url in [
            reverse("competitions:manage_list"),
            reverse("competitions:competition_create"),
            reverse("competitions:manage_competition", args=[self.comp.pk]),
            reverse("competitions:manage_registration", args=[registration.pk]),
            reverse("competitions:export_rosters", args=[self.comp.pk]),
            reverse("competitions:game_list"),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        response = self.client.post(
            reverse("competitions:manage_registration", args=[registration.pk]), {"action": "approve"}
        )
        self.assertEqual(response.status_code, 403)

    def test_public_pages_never_show_students_or_coach_contacts(self):
        registration = self.submitted()
        services.approve(REQ, registration, self.admin, division=self.division)
        Competition.objects.filter(pk=self.comp.pk).update(show_teams_publicly=True)
        self.client.logout()
        for url in [
            reverse("core:home"),
            reverse("competitions:list"),
            reverse("competitions:detail", args=[self.comp.pk]),
        ]:
            with self.subTest(url=url):
                body = self.client.get(url).content.decode()
                for private in ["Ana0", "Player0#NA1", "coach.a@example.org", "Grade 9"]:
                    self.assertNotIn(private, body)
        body = self.client.get(reverse("competitions:detail", args=[self.comp.pk])).content.decode()
        self.assertIn("Team One", body)
        self.assertIn("School A", body)

    def test_teams_are_hidden_publicly_unless_admins_turn_it_on(self):
        registration = self.submitted()
        services.approve(REQ, registration, self.admin)
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("competitions:detail", args=[self.comp.pk])), "Team One")

    def test_unpublished_competitions_are_hidden_from_coaches_and_public(self):
        Competition.objects.filter(pk=self.comp.pk).update(is_published=False)
        url = reverse("competitions:detail", args=[self.comp.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.coach_a)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)


# ------------------------------------------------------------------ the full workflow through the screens


class EndToEndTests(CompetitionTestData):
    def test_coach_registers_and_admin_approves_through_the_screens(self):
        self.client.force_login(self.coach_a)
        response = self.client.post(
            reverse("competitions:register", args=[self.comp.pk]),
            {"school": self.school_a.pk, "team_name": "Lynx Purple"},
        )
        registration = Registration.objects.get(team_name="Lynx Purple")
        self.assertRedirects(response, reverse("competitions:registration", args=[registration.pk]))

        add_url = reverse("competitions:add_player", args=[registration.pk])
        for student in self.students_a[:4]:
            self.client.post(add_url, {"student": student.pk, "gamer_tag": f"{student.first_name}#NA1"})
        # A brand-new student added in the same step
        self.client.post(add_url, {"first_name": "Newbie", "last_initial": "n", "grade": 11, "gamer_tag": "New#1"})
        self.assertEqual(registration.roster.count(), 5)
        self.assertEqual(Student.objects.get(first_name="Newbie").last_initial, "N")

        self.client.post(reverse("competitions:submit", args=[registration.pk]), {"consent": "on"})
        registration.refresh_from_db()
        self.assertEqual(registration.status, Registration.Status.SUBMITTED)

        self.client.force_login(self.admin)
        page = self.client.get(reverse("competitions:manage_registration", args=[registration.pk]))
        self.assertContains(page, "Ready to approve")
        self.client.post(
            reverse("competitions:manage_registration", args=[registration.pk]),
            {"action": "approve", "division": self.division.pk, "message": ""},
        )
        registration.refresh_from_db()
        self.assertEqual((registration.status, registration.division), (Registration.Status.APPROVED, self.division))

        self.client.force_login(self.coach_a)
        self.assertContains(self.client.get(reverse("core:coach_dashboard")), "Lynx Purple")

    def test_failed_add_does_not_leave_a_stray_student_record(self):
        registration = self.register()
        self.client.force_login(self.coach_a)
        self.client.post(
            reverse("competitions:add_player", args=[registration.pk]),
            {"first_name": "Tooyoung", "last_initial": "T", "grade": 7, "gamer_tag": "x"},
        )
        self.assertFalse(Student.objects.filter(first_name="Tooyoung").exists())

    def test_roster_export_is_admin_only_and_logged(self):
        self.submitted()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("competitions:export_rosters", args=[self.comp.pk]))
        body = response.content.decode("utf-8-sig")
        self.assertIn("Riot ID", body)
        self.assertIn("Player0#NA1", body)
        self.assertTrue(AuditEvent.objects.filter(action="export.downloaded", actor=self.admin).exists())

    def test_admin_places_teams_in_divisions_from_the_competition_page(self):
        registration = self.submitted()
        self.client.force_login(self.admin)
        self.client.post(
            reverse("competitions:assign_divisions", args=[self.comp.pk]),
            {f"division-{registration.pk}": self.division.pk},
        )
        registration.refresh_from_db()
        self.assertEqual(registration.division, self.division)
        self.assertTrue(AuditEvent.objects.filter(action="registration.division_assigned").exists())
