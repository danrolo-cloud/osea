import datetime

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from competitions.models import Competition

from . import generators, results, services, standings
from .models import Match, ResultSubmission, Stage, StageTeam, Tiebreaker
from .tests import REQ, StageTestData


class ScoreCheckTests(SimpleTestCase):
    def stage(self, best_of):
        return Stage(format=Stage.Format.ROUND_ROBIN, best_of=best_of, competition=Competition(best_of=None))

    def test_best_of_rules(self):
        bo3 = self.stage(3)
        for ok in [(2, 0), (2, 1), (0, 2), (1, 2)]:
            results.check_score(bo3, *ok, [])
        for bad in [(1, 0), (3, 0), (2, 2), (1, 1), (2, 3)]:
            with self.subTest(score=bad), self.assertRaises(ValidationError):
                results.check_score(bo3, *bad, [])

    def test_game_scores_must_agree_with_games_won(self):
        bo3 = self.stage(3)
        results.check_score(bo3, 2, 1, [[13, 11], [9, 13], [13, 7]])
        for games in ([[13, 11], [13, 9]], [[11, 13], [9, 13], [13, 7]], [[13, 13], [9, 13], [13, 7]]):
            with self.subTest(games=games), self.assertRaises(ValidationError):
                results.check_score(bo3, 2, 1, games)

    def test_parsing_game_scores(self):
        self.assertEqual(results.parse_game_scores("13-11, 9–13; 13 - 7"), [[13, 11], [9, 13], [13, 7]])
        self.assertEqual(results.parse_game_scores(""), [])
        with self.assertRaises(ValidationError):
            results.parse_game_scores("13 to 11")


class SwissPairingTests(SimpleTestCase):
    def test_avoids_rematches_and_gives_the_bye_to_lowest_without_one(self):
        played = {frozenset((1, 2)), frozenset((3, 4))}
        pairs, bye = generators.swiss_pairings([1, 2, 3, 4, 5], played, had_bye={5})
        self.assertEqual(bye, 4)  # 5 already had a bye
        self.assertEqual(pairs, [(1, 3), (2, 5)])
        for pair in pairs:
            self.assertNotIn(frozenset(pair), played)


class ResultFlowTests(StageTestData):
    def setUp(self):
        self.rr = self.stage(Stage.Format.ROUND_ROBIN, teams=self.teams[:4])
        self.match = next(m for m in self.rr.matches.filter(status="open") if m.home.school_id != m.away.school_id)
        self.home_coach = self.coaches[self.schools.index(self.match.home.school)]
        self.away_coach = self.coaches[self.schools.index(self.match.away.school)]

    def test_submit_then_confirm_makes_it_final(self):
        with self.captureOnCommitCallbacks(execute=True):
            submission = results.submit_result(REQ, self.match, self.home_coach, 2, 1, [[13, 9], [8, 13], [13, 11]])
        self.assertIn(self.away_coach.email, mail.outbox[-1].to)
        self.match.refresh_from_db()
        self.assertEqual(self.match.state, Match.State.RESULT_PENDING)
        self.assertFalse(self.match.has_result)  # not final until confirmed
        with self.captureOnCommitCallbacks(execute=True):
            results.confirm_result(REQ, submission, self.away_coach)
        self.match.refresh_from_db()
        self.assertEqual((self.match.status, self.match.winner), (Match.Status.COMPLETED, self.match.home))
        self.assertEqual(self.match.score_label, "2–1")
        submission.refresh_from_db()
        self.assertEqual(submission.status, ResultSubmission.Status.CONFIRMED)
        self.assertTrue(AuditEvent.objects.filter(action="match.result_final", actor=self.away_coach).exists())

    def test_the_submitting_side_cannot_confirm_its_own_result(self):
        submission = results.submit_result(REQ, self.match, self.home_coach, 2, 0)
        with self.assertRaisesMessage(ValidationError, "other team's coaches"):
            results.confirm_result(REQ, submission, self.home_coach)

    def test_other_schools_cannot_report(self):
        with self.assertRaises(ValidationError):
            results.submit_result(REQ, self.match, self.outsider, 2, 0)

    def test_dispute_needs_a_reason_and_goes_to_the_admin_queue(self):
        submission = results.submit_result(REQ, self.match, self.home_coach, 2, 0)
        with self.assertRaises(ValidationError):
            results.dispute_result(REQ, submission, self.away_coach, " ")
        results.dispute_result(REQ, submission, self.away_coach, "We won game 2")
        self.assertIn(submission, list(results.needs_admin()))
        self.match.refresh_from_db()
        self.assertEqual(self.match.state, Match.State.DISPUTED)

    def test_unconfirmed_results_reach_the_admin_after_48_hours(self):
        submission = results.submit_result(REQ, self.match, self.home_coach, 2, 0)
        self.assertNotIn(submission, list(results.needs_admin()))
        later = timezone.now() + datetime.timedelta(hours=49)
        self.assertIn(submission, list(results.needs_admin(now=later)))
        results.admin_accept_submission(REQ, submission, self.admin)
        self.match.refresh_from_db()
        self.assertTrue(self.match.has_result)
        submission.refresh_from_db()
        self.assertEqual(submission.status, ResultSubmission.Status.ACCEPTED_BY_OSEA)

    def test_admin_forfeit_uses_the_games_needed_to_win(self):
        results.admin_forfeit(REQ, self.match, self.admin, self.match.home, "No-show")
        self.match.refresh_from_db()
        self.assertEqual((self.match.status, self.match.winner), (Match.Status.FORFEIT, self.match.away))
        self.assertEqual((self.match.home_games, self.match.away_games), (0, 2))  # best of 3

    def test_admin_can_correct_and_reopen_with_a_reason(self):
        results.admin_set_result(REQ, self.match, self.admin, 2, 0)
        results.admin_set_result(REQ, self.match, self.admin, 0, 2)
        self.match.refresh_from_db()
        self.assertEqual(self.match.winner, self.match.away)
        with self.assertRaises(ValidationError):
            results.reopen_result(REQ, self.match, self.admin, "")
        results.reopen_result(REQ, self.match, self.admin, "Entered by mistake")
        self.match.refresh_from_db()
        self.assertEqual(self.match.status, Match.Status.OPEN)

    def test_results_need_a_published_stage(self):
        Stage.objects.filter(pk=self.rr.pk).update(is_published=False)
        self.match.refresh_from_db()
        with self.assertRaises(ValidationError):
            results.submit_result(REQ, self.match, self.home_coach, 2, 0)

    def test_coach_submits_and_confirms_through_the_screens(self):
        self.client.force_login(self.home_coach)
        self.client.post(
            reverse("matches:submit_result", args=[self.match.pk]),
            {"home_games": 2, "away_games": 1, "game_scores": "13-9, 8-13, 13-11"},
        )
        submission = self.match.submissions.get()
        self.client.force_login(self.away_coach)
        self.client.post(reverse("matches:confirm_result", args=[self.match.pk, submission.pk]))
        self.match.refresh_from_db()
        self.assertEqual(self.match.score_label, "2–1")
        self.client.force_login(self.outsider)
        response = self.client.post(
            reverse("matches:submit_result", args=[self.match.pk]), {"home_games": 0, "away_games": 2}
        )
        self.assertEqual(response.status_code, 403)


class BracketAdvancementTests(StageTestData):
    def finish(self, match, winner_is_home=True):
        match.refresh_from_db()
        results.admin_set_result(REQ, match, self.admin, 2 if winner_is_home else 0, 0 if winner_is_home else 2)

    def test_winners_and_losers_move_on_and_grand_final_reset(self):
        stage = self.stage(Stage.Format.DOUBLE_ELIMINATION, teams=self.teams[:4])
        by_number = lambda n: stage.matches.get(number=n)  # noqa: E731
        # 4 teams: WB semis 1 & 2, WB final 3, LB 4 (losers of 1 & 2), LB final 5, grand final 6
        self.finish(by_number(1))  # seed 1 beats seed 4
        self.finish(by_number(2))  # seed 2 beats seed 3
        self.assertEqual(by_number(3).home, self.teams[0])
        self.assertEqual(by_number(3).away, self.teams[1])
        self.assertEqual({by_number(4).home, by_number(4).away}, {self.teams[3], self.teams[2]})
        self.finish(by_number(3))  # seed 1 wins the winners bracket
        self.finish(by_number(4))
        self.assertEqual(by_number(5).away, self.teams[1])  # loser of the winners final drops in
        self.finish(by_number(5), winner_is_home=False)  # seed 2 wins the losers bracket
        final = by_number(6)
        self.assertEqual((final.home, final.away), (self.teams[0], self.teams[1]))
        self.finish(final, winner_is_home=False)  # losers-bracket champion wins: reset needed
        reset = stage.matches.get(is_reset=True)
        self.assertEqual((reset.home, reset.away), (self.teams[0], self.teams[1]))

    def test_results_feeding_later_decided_matches_are_protected(self):
        stage = self.stage(Stage.Format.SINGLE_ELIMINATION, teams=self.teams[:4])
        first, second, final = (stage.matches.get(number=n) for n in (1, 2, 3))
        self.finish(first)
        self.finish(second)
        self.finish(final)
        first.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "Reopen it first"):
            results.admin_set_result(REQ, first, self.admin, 0, 2)
        results.reopen_result(REQ, stage.matches.get(number=3), self.admin, "Mistake")
        results.admin_set_result(REQ, first, self.admin, 0, 2)  # now allowed, and the final updates
        self.assertEqual(stage.matches.get(number=3).home, first.away)

    def test_reopening_clears_the_team_that_moved_on(self):
        stage = self.stage(Stage.Format.SINGLE_ELIMINATION, teams=self.teams[:4])
        first = stage.matches.get(number=1)
        self.finish(first)
        self.assertIsNotNone(stage.matches.get(number=3).home)
        results.reopen_result(REQ, first, self.admin, "Replay ordered")
        self.assertIsNone(stage.matches.get(number=3).home)


class StandingsTests(StageTestData):
    def table(self, stage):
        return [(row.team.team_name, row.points, row.tied) for row in standings.calculate(stage)]

    def test_points_and_head_to_head(self):
        stage = self.stage(Stage.Format.ROUND_ROBIN, teams=self.teams[:3])  # T1, T2, T3
        t1, t2, t3 = self.teams[:3]

        def play(a, b, a_games, b_games):
            match = stage.matches.get(home__in=[a, b], away__in=[a, b])
            home_games, away_games = (a_games, b_games) if match.home == a else (b_games, a_games)
            results.admin_set_result(REQ, match, self.admin, home_games, away_games)

        play(t1, t2, 2, 0)
        play(t2, t3, 2, 0)
        play(t3, t1, 2, 1)
        # Everyone 1-1. Head-to-head among all three is level too, so game difference decides:
        # T1 +1 (2-0, 1-2), T2 0 (0-2, 2-0), T3 -1 (0-2, 2-1)
        self.assertEqual([name for name, *_ in self.table(stage)], ["Team 1", "Team 2", "Team 3"])

    def test_admin_decision_settles_a_complete_tie(self):
        stage = self.stage(Stage.Format.ROUND_ROBIN, teams=self.teams[:2])
        Stage.objects.filter(pk=stage.pk).update(tiebreakers=[])
        stage.refresh_from_db()
        rows = standings.calculate(stage)
        self.assertTrue(all(row.tied for row in rows))  # no results yet: everyone level, flagged
        StageTeam.objects.filter(stage=stage, registration=self.teams[1]).update(tiebreak_rank=1)
        StageTeam.objects.filter(stage=stage, registration=self.teams[0]).update(tiebreak_rank=2)
        rows = standings.calculate(stage)
        self.assertEqual([row.team for row in rows], [self.teams[1], self.teams[0]])
        self.assertFalse(any(row.tied for row in rows))

    def test_tiebreaker_order_is_the_admins_choice(self):
        stage = self.stage(Stage.Format.ROUND_ROBIN, teams=self.teams[:4])
        t1, t2, t3, t4 = self.teams[:4]
        scores = {
            (t1, t3): (2, 1, [[13, 2], [5, 13], [13, 3]]),
            (t2, t4): (2, 0, [[13, 11], [13, 11]]),
            (t1, t4): (0, 2, []),
            (t2, t3): (0, 2, []),
            (t1, t2): (2, 0, []),
            (t3, t4): (2, 0, []),
        }
        for (a, b), (ag, bg, games) in scores.items():
            match = stage.matches.get(home__in=[a, b], away__in=[a, b])
            if match.home == a:
                results.admin_set_result(REQ, match, self.admin, ag, bg, games)
            else:
                results.admin_set_result(REQ, match, self.admin, bg, ag, [[y, x] for x, y in games])
        Stage.objects.filter(pk=stage.pk).update(tiebreakers=[Tiebreaker.GAME_DIFF])
        stage.refresh_from_db()
        first = standings.calculate(stage)[0].team
        Stage.objects.filter(pk=stage.pk).update(tiebreakers=[Tiebreaker.SCORE_DIFF])
        stage.refresh_from_db()
        self.assertIsNotNone(first)
        self.assertEqual(len(standings.calculate(stage)), 4)

    def test_byes_only_count_when_the_stage_says_so(self):
        stage = self.stage(Stage.Format.ROUND_ROBIN, teams=self.teams[:3])
        self.assertTrue(all(row.points == 0 for row in standings.calculate(stage)))
        Stage.objects.filter(pk=stage.pk).update(bye_counts_as_win=True)
        stage.refresh_from_db()
        self.assertEqual(sum(row.points for row in standings.calculate(stage)), 3)  # three byes in three rounds


class SwissRoundTests(StageTestData):
    def test_next_round_needs_finished_results_and_avoids_rematches(self):
        stage = self.stage(Stage.Format.SWISS, teams=self.teams, swiss_rounds=3)
        with self.assertRaisesMessage(ValidationError, "without a final result"):
            results.pair_next_swiss_round(stage, self.admin)
        for match in stage.matches.filter(status="open"):
            results.admin_set_result(REQ, match, self.admin, 2, 0)
        results.pair_next_swiss_round(stage, self.admin)
        round_two = stage.matches.filter(round_number=2)
        self.assertEqual(round_two.count(), 3)
        first = {frozenset((m.home_id, m.away_id)) for m in stage.matches.filter(round_number=1)}
        for match in round_two:
            self.assertNotIn(frozenset((match.home_id, match.away_id)), first)
        winners = {m.winner_id for m in stage.matches.filter(round_number=1)}
        # Teams meet teams with the same record; with three 1-0 teams, exactly one has to play a 0-1 team.
        mixed = [m for m in round_two if (m.home_id in winners) != (m.away_id in winners)]
        self.assertEqual(len(mixed), 1)
        self.assertTrue(AuditEvent.objects.filter(action="stage.swiss_paired").exists())

    def test_cannot_go_past_the_number_of_rounds(self):
        stage = self.stage(Stage.Format.SWISS, teams=self.teams[:4], swiss_rounds=1)
        for match in stage.matches.filter(status="open"):
            results.admin_set_result(REQ, match, self.admin, 2, 0)
        with self.assertRaisesMessage(ValidationError, "All 1 Swiss rounds"):
            results.pair_next_swiss_round(stage, self.admin)


class ResultQueueVisibilityTests(StageTestData):
    def test_admin_result_pages_refuse_coaches(self):
        stage = self.stage(Stage.Format.ROUND_ROBIN, teams=self.teams[:4])
        match = stage.matches.filter(status="open").first()
        self.client.force_login(self.coaches[0])
        for method, url in [
            ("get", reverse("matches:results_queue")),
            ("post", reverse("matches:admin_result", args=[match.pk])),
            ("post", reverse("matches:swiss_next_round", args=[stage.pk])),
            ("post", reverse("matches:tiebreak", args=[stage.pk])),
        ]:
            with self.subTest(url=url):
                response = getattr(self.client, method)(url, {"action": "set", "home_games": 2, "away_games": 0})
                self.assertEqual(response.status_code, 403)
        match.refresh_from_db()
        self.assertFalse(match.has_result)
        self.assertEqual(services.coached_sides(self.outsider, match), [])


class StageSettingsTests(StageTestData):
    def post(self, **extra):
        data = {"name": "League", "format": "round_robin", "order": 1, "points_win": 3, "points_loss": 0}
        data.update(extra)
        self.client.force_login(self.admin)
        return self.client.post(reverse("matches:stage_create", args=[self.comp.pk]), data)

    def test_tiebreaker_order_is_saved_as_chosen(self):
        self.post(tiebreaker_1="buchholz", tiebreaker_2="head_to_head", tiebreaker_3="")
        stage = Stage.objects.get(name="League")
        self.assertEqual(stage.tiebreakers, ["buchholz", "head_to_head"])
        self.assertEqual(stage.points_win, 3)

    def test_a_tiebreaker_cannot_be_used_twice(self):
        response = self.post(tiebreaker_1="game_diff", tiebreaker_2="game_diff")
        self.assertContains(response, "can only be used once")
        self.assertFalse(Stage.objects.filter(name="League").exists())
