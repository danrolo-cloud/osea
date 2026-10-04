import datetime
from collections import Counter

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from competitions.models import Announcement, Competition, Division, Game, Registration
from schools.models import CoachAccess, School, SchoolYear

from . import generators, services
from .models import Match, Stage, TimeProposal

NOW = timezone.now()
PASSWORD = "a-long-test-password"


class FakeRequest:
    def build_absolute_uri(self, path):
        return "https://osea.example" + path


REQ = FakeRequest()


# ------------------------------------------------------------------ pure format generators


class RoundRobinGeneratorTests(SimpleTestCase):
    def test_everyone_plays_everyone_once_and_never_twice_in_a_round(self):
        for n in range(2, 13):
            with self.subTest(teams=n):
                plans = generators.round_robin(list(range(1, n + 1)))
                games = [frozenset((p["home"], p["away"])) for p in plans if p["away"] is not None]
                self.assertEqual(len(games), n * (n - 1) // 2)
                self.assertEqual(len(set(games)), len(games))
                for rnd in {p["round"] for p in plans}:
                    playing = [t for p in plans if p["round"] == rnd for t in (p["home"], p["away"]) if t]
                    self.assertEqual(len(playing), len(set(playing)))

    def test_odd_numbers_give_one_bye_per_round(self):
        plans = generators.round_robin([1, 2, 3, 4, 5])
        byes = [p for p in plans if p["away"] is None]
        self.assertEqual(len(byes), 5)  # 5 rounds, one bye each
        self.assertEqual(sorted(p["home"] for p in byes), [1, 2, 3, 4, 5])  # everyone sits out once

    def test_double_round_robin_repeats_each_pairing_with_sides_swapped(self):
        plans = generators.round_robin([1, 2, 3, 4], twice=True)
        games = Counter((p["home"], p["away"]) for p in plans)
        self.assertEqual(len(plans), 12)
        for (home, away), count in games.items():
            self.assertEqual(count, 1)
            self.assertIn((away, home), games)


class EliminationGeneratorTests(SimpleTestCase):
    def test_standard_seeding_keeps_top_seeds_apart(self):
        self.assertEqual(generators.seeding_positions(8), [1, 8, 4, 5, 2, 7, 3, 6])

    def test_single_elimination_gives_byes_to_top_seeds(self):
        plans = generators.single_elimination([1, 2, 3, 4, 5, 6])
        first = [(p["home"], p["away"]) for p in plans if p["round"] == 1]
        self.assertEqual(first, [(1, None), (4, 5), (2, None), (3, 6)])
        self.assertEqual(len(plans), 7)
        self.assertEqual(plans[-1]["label"], "Final")

    def test_double_elimination_shape_for_every_field_size(self):
        for n in range(3, 33):
            with self.subTest(teams=n):
                plans = generators.double_elimination(list(range(1, n + 1)))
                size = 2 ** (n - 1).bit_length()
                self.assertEqual(len(plans), 2 * size - 2)  # winners + losers + grand final
                seen, feeds = set(), Counter()
                for p in plans:
                    for link in (p["home_from"], p["away_from"]):
                        if link:
                            self.assertIn(link[0], seen)  # always fed by an earlier match
                            feeds[link] += 1
                    seen.add(p["key"])
                self.assertEqual(max(feeds.values()), 1)  # each winner/loser goes to exactly one place
                self.assertEqual(plans[-1]["bracket"], "final")

    def test_swiss_round_one_pairs_top_half_with_bottom_half(self):
        plans = generators.swiss_first_round([1, 2, 3, 4, 5, 6, 7])
        self.assertEqual([(p["home"], p["away"]) for p in plans], [(1, 4), (2, 5), (3, 6), (7, None)])

    def test_too_few_teams(self):
        with self.assertRaises(ValueError):
            generators.double_elimination([1, 2])
        with self.assertRaises(ValueError):
            generators.single_elimination([1])


# ------------------------------------------------------------------ database: stages, matches, scheduling


def make_user(email, role=User.Role.COACH):
    return User.objects.create_user(
        email=email, password=PASSWORD, first_name=email[:4].title(), last_name="T", role=role, email_verified_at=NOW
    )


class StageTestData(TestCase):
    """Six approved teams from four schools in one competition; coach A coaches two of them."""

    @classmethod
    def setUpTestData(cls):
        year = SchoolYear.objects.create(
            name="2026–27", start_date=datetime.date(2026, 9, 1), end_date=datetime.date(2027, 6, 30), is_current=True
        )
        game = Game.objects.create(name="Valorant")
        cls.comp = Competition.objects.create(
            school_year=year, game=game, name="League", registration_opens_at=NOW - datetime.timedelta(days=30),
            registration_closes_at=NOW - datetime.timedelta(days=10), roster_deadline=NOW + datetime.timedelta(days=30),
            allowed_levels=["secondary"], min_grade=9, max_grade=12, players_per_team=5, roster_min=5, roster_max=7,
            is_published=True, best_of=3,
        )  # fmt: skip
        cls.div = Division.objects.create(competition=cls.comp, name="Gold")
        cls.admin = make_user("admin@example.org", User.Role.ADMIN)
        cls.schools, cls.coaches = [], []
        for i in range(4):
            school = School.objects.create(name=f"School {i}", city="X", level="secondary")
            coach = make_user(f"coach{i}@example.org")
            CoachAccess.objects.create(coach=coach, school=school, position="T", status=CoachAccess.Status.APPROVED)
            cls.schools.append(school)
            cls.coaches.append(coach)
        owners = [0, 1, 2, 3, 0, 1]  # school 0 and school 1 each have two teams
        cls.teams = [
            Registration.objects.create(
                competition=cls.comp,
                school=cls.schools[s],
                team_name=f"Team {i + 1}",
                status="approved",
                division=cls.div,
                created_by=cls.coaches[s],
            )  # fmt: skip
            for i, s in enumerate(owners)
        ]
        cls.outsider = make_user("outsider@example.org")
        outsider_school = School.objects.create(name="Outside", city="X", level="secondary")
        CoachAccess.objects.create(
            coach=cls.outsider, school=outsider_school, position="T", status=CoachAccess.Status.APPROVED
        )

    def stage(self, fmt, teams=None, published=True, **extra):
        stage = Stage.objects.create(competition=self.comp, name=fmt, format=fmt, is_published=published, **extra)
        services.generate_stage(
            stage, self.admin, teams or self.teams, first_day=datetime.date(2026, 11, 2), days_per_round=7
        )
        return stage


class GenerateStageTests(StageTestData):
    def test_round_robin_with_five_teams_has_a_bye_each_round(self):
        stage = self.stage(Stage.Format.ROUND_ROBIN, teams=self.teams[:5])
        self.assertEqual(stage.matches.count(), 15)  # 5 rounds x 3 slots
        byes = stage.matches.filter(status=Match.Status.BYE)
        self.assertEqual(byes.count(), 5)
        self.assertTrue(all(m.winner == m.home and m.away is None for m in byes))
        self.assertEqual(stage.entries.count(), 5)

    def test_single_elimination_byes_send_top_seeds_through(self):
        stage = self.stage(Stage.Format.SINGLE_ELIMINATION)
        first = stage.matches.filter(round_number=1).order_by("number")
        self.assertEqual([m.status for m in first], ["bye", "open", "bye", "open"])
        semis = stage.matches.filter(round_number=2).order_by("number")
        self.assertEqual(semis[0].home, self.teams[0])  # seed 1 is already in the semifinal
        self.assertIsNone(semis[0].away)  # waiting for the 4 v 5 winner
        self.assertEqual(semis[0].state, Match.State.WAITING)
        self.assertEqual(semis[1].home, self.teams[1])  # seed 2

    def test_double_elimination_handles_byes_in_the_losers_bracket(self):
        stage = self.stage(Stage.Format.DOUBLE_ELIMINATION)
        self.assertEqual(stage.matches.count(), 14)
        losers_round_1 = stage.matches.filter(bracket="losers", round_number=2).order_by("number")
        # Both first-round byes feed "loser of" slots that will never have a team.
        self.assertTrue(all(m.state in (Match.State.WAITING, Match.State.BYE) for m in losers_round_1))
        final = stage.matches.get(bracket="final")
        self.assertIsNotNone(final.home_source)
        self.assertIsNotNone(final.away_source)

    def test_play_windows_follow_the_days_per_round_in_toronto_time(self):
        stage = self.stage(Stage.Format.ROUND_ROBIN, teams=self.teams[:4])
        first = stage.matches.filter(round_number=1).first()
        second = stage.matches.filter(round_number=2).first()
        self.assertEqual(timezone.localtime(first.play_from).strftime("%Y-%m-%d %H:%M"), "2026-11-02 00:00")
        self.assertEqual(timezone.localtime(first.play_by).strftime("%Y-%m-%d %H:%M"), "2026-11-08 23:59")
        self.assertEqual(timezone.localtime(second.play_from).strftime("%Y-%m-%d"), "2026-11-09")

    def test_generation_rules(self):
        stage = self.stage(Stage.Format.ROUND_ROBIN, teams=self.teams[:4])
        with self.assertRaisesMessage(ValidationError, "already has matches"):
            services.generate_stage(
                stage, self.admin, self.teams[:4], first_day=datetime.date(2026, 11, 2), days_per_round=7
            )
        custom = Stage.objects.create(competition=self.comp, name="c", format=Stage.Format.CUSTOM)
        with self.assertRaises(ValidationError):
            services.generate_stage(
                custom, self.admin, self.teams, first_day=datetime.date(2026, 11, 2), days_per_round=7
            )
        withdrawn = Registration.objects.create(
            competition=self.comp, school=self.schools[2], team_name="Gone", status="withdrawn", created_by=self.admin
        )
        fresh = Stage.objects.create(competition=self.comp, name="f", format=Stage.Format.ROUND_ROBIN)
        with self.assertRaisesMessage(ValidationError, "Only approved teams"):
            services.generate_stage(
                fresh, self.admin, [*self.teams[:3], withdrawn], first_day=datetime.date(2026, 11, 2), days_per_round=7
            )

    def test_clearing_a_stage_is_logged(self):
        stage = self.stage(Stage.Format.ROUND_ROBIN, teams=self.teams[:4])
        services.clear_stage(stage, self.admin)
        self.assertFalse(stage.matches.exists())
        self.assertTrue(AuditEvent.objects.filter(action="stage.cleared", actor=self.admin).exists())


class SchedulingTests(StageTestData):
    def setUp(self):
        self.round_robin = self.stage(Stage.Format.ROUND_ROBIN, teams=self.teams[:4])
        # Team 1 (school 0) v Team 2 (school 1) or similar: pick a playable match between two different schools.
        self.match = next(
            m for m in self.round_robin.matches.filter(status="open")
            if m.home.school_id != m.away.school_id
        )  # fmt: skip
        self.home_coach = self.coaches[self.schools.index(self.match.home.school)]
        self.away_coach = self.coaches[self.schools.index(self.match.away.school)]
        self.when = NOW + datetime.timedelta(days=3)

    def test_coaches_agree_on_a_time_without_admin_approval(self):
        with self.captureOnCommitCallbacks(execute=True):
            proposal = services.propose_time(REQ, self.match, self.home_coach, self.when, "After school?")
        self.assertIn(self.away_coach.email, mail.outbox[-1].to)
        with self.captureOnCommitCallbacks(execute=True):
            services.accept_proposal(REQ, proposal, self.away_coach)
        self.match.refresh_from_db()
        self.assertEqual(self.match.scheduled_at, self.when)
        self.assertEqual(self.match.state, Match.State.SCHEDULED)
        self.assertIn(self.home_coach.email, mail.outbox[-1].to)
        self.assertTrue(AuditEvent.objects.filter(action="match.time_agreed", actor=self.away_coach).exists())

    def test_the_proposing_side_cannot_accept_its_own_proposal(self):
        proposal = services.propose_time(REQ, self.match, self.home_coach, self.when)
        with self.assertRaisesMessage(ValidationError, "other team's coaches"):
            services.accept_proposal(REQ, proposal, self.home_coach)

    def test_coaches_of_other_schools_cannot_propose_or_answer(self):
        with self.assertRaises(ValidationError):
            services.propose_time(REQ, self.match, self.outsider, self.when)
        proposal = services.propose_time(REQ, self.match, self.home_coach, self.when)
        with self.assertRaises(ValidationError):
            services.accept_proposal(REQ, proposal, self.outsider)

    def test_times_must_be_in_the_future(self):
        with self.assertRaisesMessage(ValidationError, "in the future"):
            services.propose_time(REQ, self.match, self.home_coach, NOW - datetime.timedelta(hours=1))

    def test_rescheduling_keeps_the_agreed_time_until_the_new_one_is_accepted(self):
        first = services.propose_time(REQ, self.match, self.home_coach, self.when)
        services.accept_proposal(REQ, first, self.away_coach)
        later = self.when + datetime.timedelta(days=1)
        second = services.propose_time(REQ, self.match, self.away_coach, later)
        self.match.refresh_from_db()
        self.assertEqual(self.match.scheduled_at, self.when)  # unchanged until accepted
        services.accept_proposal(REQ, second, self.home_coach)
        self.match.refresh_from_db()
        self.assertEqual(self.match.scheduled_at, later)

    def test_a_new_proposal_replaces_the_pending_one(self):
        first = services.propose_time(REQ, self.match, self.home_coach, self.when)
        services.propose_time(REQ, self.match, self.away_coach, self.when + datetime.timedelta(hours=2))
        first.refresh_from_db()
        self.assertEqual(first.status, TimeProposal.Status.REPLACED)
        with self.assertRaises(ValidationError):
            services.accept_proposal(REQ, first, self.away_coach)

    def test_decline_and_withdraw(self):
        proposal = services.propose_time(REQ, self.match, self.home_coach, self.when)
        services.decline_proposal(REQ, proposal, self.away_coach, "Exams that week")
        proposal.refresh_from_db()
        self.assertEqual((proposal.status, proposal.response_note), ("declined", "Exams that week"))
        another = services.propose_time(REQ, self.match, self.home_coach, self.when)
        with self.assertRaises(ValidationError):
            services.withdraw_proposal(another, self.away_coach)
        services.withdraw_proposal(another, self.home_coach)

    def test_admin_can_set_a_time_which_replaces_pending_proposals(self):
        proposal = services.propose_time(REQ, self.match, self.home_coach, self.when)
        services.set_time(REQ, self.match, self.admin, self.when + datetime.timedelta(days=2))
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, TimeProposal.Status.REPLACED)
        self.assertTrue(AuditEvent.objects.filter(action="match.time_set", actor=self.admin).exists())

    def test_cancelled_matches_cannot_be_scheduled_until_restored(self):
        with self.assertRaises(ValidationError):
            services.cancel_match(REQ, self.match, self.admin, " ")
        services.cancel_match(REQ, self.match, self.admin, "Snow day")
        with self.assertRaises(ValidationError):
            services.propose_time(REQ, self.match, self.home_coach, self.when)
        services.restore_match(self.match, self.admin)
        services.propose_time(REQ, self.match, self.home_coach, self.when)

    def test_proposed_times_are_read_as_toronto_time_across_daylight_saving(self):
        self.client.force_login(self.home_coach)
        future = timezone.localdate() + datetime.timedelta(days=400)
        winter = datetime.date(future.year, 1, 15)
        self.client.post(
            reverse("matches:propose", args=[self.match.pk]), {"proposed_time": f"{winter:%Y-%m-%d}T19:00", "note": ""}
        )
        proposal = self.match.proposals.get()
        self.assertEqual(proposal.proposed_time.astimezone(datetime.UTC).hour, 0)  # 7 p.m. EST = 00:00 UTC
        summer = datetime.date(future.year, 7, 15)
        self.client.post(
            reverse("matches:propose", args=[self.match.pk]), {"proposed_time": f"{summer:%Y-%m-%d}T19:00", "note": ""}
        )
        latest = self.match.proposals.order_by("-created_at").first()
        self.assertEqual(latest.proposed_time.astimezone(datetime.UTC).hour, 23)  # 7 p.m. EDT = 23:00 UTC

    def test_two_teams_from_the_same_school_can_be_arranged_by_one_coach(self):
        same_school = Match.objects.create(
            stage=self.round_robin, number=999, home=self.teams[0], away=self.teams[4], round_label="Extra"
        )
        proposal = services.propose_time(REQ, same_school, self.coaches[0], self.when)
        services.accept_proposal(REQ, proposal, self.coaches[0])


class VisibilityTests(StageTestData):
    def test_unpublished_stages_are_hidden_from_coaches_and_the_public(self):
        stage = self.stage(Stage.Format.ROUND_ROBIN, teams=self.teams[:4], published=False)
        match = stage.matches.filter(status="open").first()
        coach = self.coaches[self.schools.index(match.home.school)]
        self.client.force_login(coach)
        self.assertEqual(self.client.get(reverse("matches:coach_match", args=[match.pk])).status_code, 403)
        self.assertNotContains(self.client.get(reverse("matches:my_matches")), match.home.team_name)
        with self.assertRaises(ValidationError):
            services.propose_time(REQ, match, coach, NOW + datetime.timedelta(days=1))
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("competitions:detail", args=[self.comp.pk])), "Match 1")

    def test_coaches_only_see_their_own_matches(self):
        stage = self.stage(Stage.Format.ROUND_ROBIN, teams=self.teams[:4])
        match = stage.matches.filter(status="open").first()
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse("matches:coach_match", args=[match.pk])).status_code, 403)
        self.assertEqual(
            self.client.post(reverse("matches:propose", args=[match.pk]), {"proposed_time": "2030-01-01T10:00"})
            .status_code, 403,
        )  # fmt: skip
        self.assertFalse(match.proposals.exists())

    def test_opposing_coach_contact_is_shared_only_within_the_match(self):
        stage = self.stage(Stage.Format.ROUND_ROBIN, teams=self.teams[:4])
        match = next(m for m in stage.matches.filter(status="open") if m.home.school_id != m.away.school_id)
        home_coach = self.coaches[self.schools.index(match.home.school)]
        away_coach = self.coaches[self.schools.index(match.away.school)]
        self.client.force_login(home_coach)
        self.assertContains(self.client.get(reverse("matches:coach_match", args=[match.pk])), away_coach.email)
        self.client.logout()
        public = self.client.get(reverse("competitions:detail", args=[self.comp.pk])).content.decode()
        self.assertIn(match.home.team_name, public)
        for coach in self.coaches:
            self.assertNotIn(coach.email, public)

    def test_stage_and_match_admin_pages_refuse_coaches(self):
        stage = self.stage(Stage.Format.ROUND_ROBIN, teams=self.teams[:4])
        match = stage.matches.first()
        self.client.force_login(self.coaches[0])
        for method, url in [
            ("get", reverse("matches:stage", args=[stage.pk])),
            ("get", reverse("matches:stage_create", args=[self.comp.pk])),
            ("post", reverse("matches:stage_generate", args=[stage.pk])),
            ("post", reverse("matches:stage_clear", args=[stage.pk])),
            ("get", reverse("matches:match_edit", args=[stage.pk, match.pk])),
            ("post", reverse("matches:match_cancel", args=[match.pk])),
            ("get", reverse("competitions:announcement_create", args=[self.comp.pk])),
        ]:
            with self.subTest(url=url):
                self.assertEqual(getattr(self.client, method)(url, {"reason": "x"}).status_code, 403)
        self.assertEqual(stage.matches.count(), 6)


class AnnouncementTests(StageTestData):
    def test_division_and_public_targeting(self):
        other_division = Division.objects.create(competition=self.comp, name="Silver")
        Announcement.objects.create(competition=self.comp, title="For everyone", body="x", created_by=self.admin)
        Announcement.objects.create(
            competition=self.comp, division=self.div, title="Gold only", body="x", created_by=self.admin
        )
        Announcement.objects.create(
            competition=self.comp, division=other_division, title="Silver only", body="x", created_by=self.admin
        )
        Announcement.objects.create(
            competition=self.comp, title="Public news", body="x", is_public=True, created_by=self.admin
        )
        self.client.force_login(self.coaches[0])  # teams in Gold
        dashboard = self.client.get(reverse("core:coach_dashboard")).content.decode()
        self.assertIn("For everyone", dashboard)
        self.assertIn("Gold only", dashboard)
        self.assertNotIn("Silver only", dashboard)
        self.client.force_login(self.outsider)  # no teams in this competition
        self.assertNotIn("For everyone", self.client.get(reverse("core:coach_dashboard")).content.decode())
        self.client.logout()
        public = self.client.get(reverse("competitions:detail", args=[self.comp.pk])).content.decode()
        self.assertIn("Public news", public)
        self.assertNotIn("For everyone", public)

    def test_admin_posts_through_the_screen_and_it_is_logged(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("competitions:announcement_create", args=[self.comp.pk]),
            {"title": "Week 1 reminder", "body": "Rules: https://example.org/rules", "division": ""},
        )
        self.assertTrue(Announcement.objects.filter(title="Week 1 reminder").exists())
        self.assertTrue(AuditEvent.objects.filter(action="announcement.posted", actor=self.admin).exists())


class AdminScreenTests(StageTestData):
    def test_admin_builds_a_stage_through_the_screens(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("matches:stage_create", args=[self.comp.pk]),
            {"name": "Playoffs", "format": "double_elim", "order": 1, "is_published": "on"},
        )
        stage = Stage.objects.get(name="Playoffs")
        data = {"first_day": "2026-11-02", "days_per_round": 7}
        for seed, team in enumerate(reversed(self.teams), start=1):
            data[f"include-{team.pk}"] = "on"
            data[f"seed-{team.pk}"] = seed
        self.client.post(reverse("matches:stage_generate", args=[stage.pk]), data)
        self.assertEqual(stage.matches.count(), 14)
        self.assertEqual(stage.entries.get(seed=1).registration, self.teams[-1])  # the admin's seeding is used
        page = self.client.get(reverse("matches:stage", args=[stage.pk]))
        self.assertContains(page, "Winners bracket")
        self.assertContains(page, "Grand final")

    def test_swiss_stage_needs_a_number_of_rounds(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("matches:stage_create", args=[self.comp.pk]), {"name": "Swiss", "format": "swiss", "order": 1}
        )
        self.assertContains(response, "how many Swiss rounds")
