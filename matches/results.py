"""
Result rules.

  - Either team's coach submits a result (games won by each side, optionally
    each game's score).
  - The other team's coach confirms it, which makes it final, or disputes it.
  - Disputed results, and results unconfirmed after 48 hours, go to OSEA's
    queue. An administrator can finalize a submitted result in one click, or
    enter, correct, reopen or record a forfeit for any match. Every change is logged.
  - Only final results count: they move winners (and losers) on in brackets
    and feed the standings.
"""

import datetime

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone
from django.utils.translation import gettext as _

from audit.log import record

from . import generators, standings
from .models import Match, ResultSubmission, Stage
from .services import _fail, _notify, coached_sides, resolve_stage

CONFIRMATION_WINDOW = datetime.timedelta(hours=48)
OPEN_SUBMISSION = [ResultSubmission.Status.PENDING, ResultSubmission.Status.DISPUTED]


# ------------------------------------------------------------------ checking scores


def parse_game_scores(text):
    """'13-11, 9-13, 13-7' -> [[13, 11], [9, 13], [13, 7]]. Blank means no per-game scores."""
    games = []
    for part in [p.strip() for p in (text or "").replace(";", ",").split(",") if p.strip()]:
        pieces = part.replace("–", "-").replace(" ", "").split("-")
        if len(pieces) != 2 or not all(p.isdigit() for p in pieces):
            _fail(_("Write each game's score like 13-11, separated by commas."))
        games.append([int(pieces[0]), int(pieces[1])])
    return games


def check_score(stage, home_games, away_games, game_scores):
    if home_games is None or away_games is None or home_games < 0 or away_games < 0:
        _fail(_("Enter the number of games each team won."))
    if home_games == away_games:
        _fail(_("A match needs a winner; draws aren't supported."))
    need = stage.games_to_win
    if stage.effective_best_of and (max(home_games, away_games) != need or min(home_games, away_games) >= need):
        _fail(
            _("In a best of %(bo)s, the winner takes exactly %(need)s games (e.g. %(need)s–0 or %(need)s–1).")
            % {"bo": stage.effective_best_of, "need": need}
        )
    if game_scores:
        if len(game_scores) != home_games + away_games:
            _fail(_("Enter a score for each game played (%(n)s games).") % {"n": home_games + away_games})
        if any(h == a for h, a in game_scores):
            _fail(_("Each game needs a winner."))
        if sum(1 for h, a in game_scores if h > a) != home_games:
            _fail(_("The game scores don't match the games won."))


# ------------------------------------------------------------------ what still needs attention


def needs_admin(now=None):
    """Open submissions OSEA should look at: disputes, and anything unconfirmed after 48 hours."""
    now = now or timezone.now()
    return ResultSubmission.objects.filter(
        Q(status=ResultSubmission.Status.DISPUTED)
        | Q(status=ResultSubmission.Status.PENDING, created_at__lt=now - CONFIRMATION_WINDOW)
    ).select_related("match__stage__competition", "match__home", "match__away", "submitting_team")


def _dependents(match):
    """Later matches that take this match's winner or loser (including a grand-final reset)."""
    linked = Q(home_source=match) | Q(away_source=match)
    if match.bracket == Match.Bracket.FINAL and not match.is_reset:
        linked |= Q(is_reset=True)
    return match.stage.matches.filter(linked).exclude(pk=match.pk)


def _check_can_change(match):
    decided = [m for m in _dependents(match) if m.has_result]
    if decided:
        _fail(
            _("Match %(n)s already has a result that depends on this one. Reopen it first.")
            % {"n": ", ".join(str(m.number) for m in decided)}
        )


# ------------------------------------------------------------------ making a result final


def _finalize(request, match, user, home_games, away_games, game_scores, status=Match.Status.COMPLETED, note=""):
    old = match.score_label
    match.home_games, match.away_games, match.game_scores = home_games, away_games, game_scores or []
    match.winner = match.home if home_games > away_games else match.away
    match.status = status
    match.finalized_at, match.finalized_by = timezone.now(), user
    match.save()
    match.submissions.filter(status__in=OPEN_SUBMISSION).update(status=ResultSubmission.Status.REPLACED)
    _grand_final_reset(match)
    resolve_stage(match.stage)
    verb = "Corrected" if old else "Final result"
    record(
        user,
        "match.result_final",
        f"{verb}: {match} of {match.stage}, {match.home.team_name} {match.score_label} {match.away.team_name}",
        target=match.stage.competition,
        changes={"result": [old, match.score_label], **({"note": ["", note]} if note else {})},
    )
    _notify(
        request,
        match.teams(),
        f"Final result: {match.home.team_name} {match.score_label} {match.away.team_name}",
        "matches/emails/result_final.txt",
        match=match,
    )
    return match


def _grand_final_reset(match):
    """Double elimination: if the losers-bracket team wins the grand final, add a second final."""
    stage = match.stage
    if (match.bracket != Match.Bracket.FINAL or match.is_reset or stage.format != Stage.Format.DOUBLE_ELIMINATION
            or not stage.grand_final_reset):  # fmt: skip
        return
    reset = stage.matches.filter(is_reset=True).first()
    if match.has_result and match.winner_id == match.away_id:  # away = winner of the losers bracket
        if reset is None:
            number = (stage.matches.aggregate(n=Max("number"))["n"] or 0) + 1
            Match.objects.create(
                stage=stage, number=number, round_number=match.round_number + 1, round_label="Grand final reset",
                bracket=Match.Bracket.FINAL, home=match.home, away=match.away, is_reset=True,
            )  # fmt: skip
    elif reset is not None and not reset.has_result:
        reset.delete()


# ------------------------------------------------------------------ coaches


def _require_reportable(match):
    if not match.stage.is_published:
        _fail(_("This match hasn't been published yet."))
    if match.status != Match.Status.OPEN or not (match.home_id and match.away_id):
        _fail(_("Results can only be reported for open matches between two known teams."))


@transaction.atomic
def submit_result(request, match, user, home_games, away_games, game_scores=None, note=""):
    match = Match.objects.select_for_update().get(pk=match.pk)
    _require_reportable(match)
    sides = coached_sides(user, match)
    if not sides:
        _fail(_("Only coaches of the two teams can report this result."))
    check_score(match.stage, home_games, away_games, game_scores)
    match.submissions.filter(status__in=OPEN_SUBMISSION).update(status=ResultSubmission.Status.REPLACED)
    team = getattr(match, sides[0])
    submission = ResultSubmission.objects.create(
        match=match, submitting_team=team, submitted_by=user, home_games=home_games, away_games=away_games,
        game_scores=game_scores or [], note=note.strip(),
    )  # fmt: skip
    record(
        user,
        "match.result_submitted",
        f"{team.team_name} reported {match} of {match.stage}: "
        f"{match.home.team_name} {home_games}–{away_games} {match.away.team_name}",
        target=match.stage.competition,
    )
    other = match.away if team == match.home else match.home
    _notify(
        request,
        [other],
        f"Please confirm: {match.home.team_name} {home_games}–{away_games} {match.away.team_name}",
        "matches/emails/result_submitted.txt",
        match=match,
        submission=submission,
    )
    return submission


def _answerable(submission, user):
    if submission.status != ResultSubmission.Status.PENDING:
        _fail(_("This result has already been answered or replaced."))
    match = submission.match
    other_side = "away" if submission.submitting_team_id == match.home_id else "home"
    if other_side not in coached_sides(user, match):
        _fail(_("Only the other team's coaches can confirm or dispute this result."))


@transaction.atomic
def confirm_result(request, submission, user):
    submission = ResultSubmission.objects.select_for_update().select_related("match__stage").get(pk=submission.pk)
    _answerable(submission, user)
    match = submission.match
    _require_reportable(match)
    submission.status = ResultSubmission.Status.CONFIRMED
    submission.responded_at, submission.responded_by = timezone.now(), user
    submission.save()
    _finalize(request, match, user, submission.home_games, submission.away_games, submission.game_scores)
    return match


@transaction.atomic
def dispute_result(request, submission, user, reason):
    submission = ResultSubmission.objects.select_for_update().select_related("match__stage").get(pk=submission.pk)
    _answerable(submission, user)
    if not reason.strip():
        _fail(_("Explain what's wrong with the reported result."))
    submission.status = ResultSubmission.Status.DISPUTED
    submission.responded_at, submission.responded_by = timezone.now(), user
    submission.dispute_reason = reason.strip()
    submission.save()
    match = submission.match
    record(
        user,
        "match.result_disputed",
        f"Disputed the reported result of {match} of {match.stage}",
        target=match.stage.competition,
        changes={"reason": ["", submission.dispute_reason]},
    )
    _notify(
        request,
        [submission.submitting_team],
        f"Result disputed: {match.home.team_name} v {match.away.team_name}",
        "matches/emails/result_disputed.txt",
        match=match,
        submission=submission,
    )
    return submission


# ------------------------------------------------------------------ administrators


@transaction.atomic
def admin_accept_submission(request, submission, admin):
    """One click: make a submitted (or disputed) result final."""
    submission = ResultSubmission.objects.select_for_update().select_related("match__stage").get(pk=submission.pk)
    if submission.status not in OPEN_SUBMISSION:
        _fail(_("This result has already been answered or replaced."))
    match = submission.match
    _finalize(
        request,
        match,
        admin,
        submission.home_games,
        submission.away_games,
        submission.game_scores,
        note="Finalized by OSEA from a coach's report",
    )
    submission.status = ResultSubmission.Status.ACCEPTED_BY_OSEA
    submission.responded_at, submission.responded_by = timezone.now(), admin
    submission.save()
    return match


@transaction.atomic
def admin_set_result(request, match, admin, home_games, away_games, game_scores=None, note=""):
    """Enter or correct a result directly."""
    match = Match.objects.select_for_update().select_related("stage").get(pk=match.pk)
    if match.status == Match.Status.CANCELLED or not (match.home_id and match.away_id):
        _fail(_("Results need two known teams and a match that isn't cancelled."))
    if match.status == Match.Status.BYE:
        _fail(_("A bye has no result."))
    check_score(match.stage, home_games, away_games, game_scores)
    if match.has_result:
        _check_can_change(match)
    match.submissions.filter(status__in=OPEN_SUBMISSION).update(status=ResultSubmission.Status.REJECTED_BY_OSEA)
    return _finalize(request, match, admin, home_games, away_games, game_scores, note=note)


@transaction.atomic
def admin_forfeit(request, match, admin, forfeiting_team, reason):
    match = Match.objects.select_for_update().select_related("stage").get(pk=match.pk)
    if forfeiting_team not in (match.home, match.away) or forfeiting_team is None:
        _fail(_("Choose one of the two teams in this match."))
    if not reason.strip():
        _fail(_("Give a reason for the forfeit."))
    if match.has_result:
        _check_can_change(match)
    need = match.stage.games_to_win
    home_games, away_games = (0, need) if forfeiting_team == match.home else (need, 0)
    match.submissions.filter(status__in=OPEN_SUBMISSION).update(status=ResultSubmission.Status.REJECTED_BY_OSEA)
    return _finalize(
        request,
        match,
        admin,
        home_games,
        away_games,
        [],
        status=Match.Status.FORFEIT,
        note=f"{forfeiting_team.team_name} forfeited: {reason.strip()}",
    )


@transaction.atomic
def reopen_result(request, match, admin, reason):
    match = Match.objects.select_for_update().select_related("stage").get(pk=match.pk)
    if not match.has_result:
        _fail(_("This match doesn't have a result."))
    if not reason.strip():
        _fail(_("Give a reason for reopening the result."))
    _check_can_change(match)
    old = match.score_label
    match.status, match.winner = Match.Status.OPEN, None
    match.home_games = match.away_games = None
    match.game_scores, match.finalized_at, match.finalized_by = [], None, None
    match.save()
    _grand_final_reset(match)
    resolve_stage(match.stage)
    record(
        admin,
        "match.result_reopened",
        f"Reopened the result of {match} of {match.stage}",
        target=match.stage.competition,
        changes={"result": [old, ""], "reason": ["", reason.strip()]},
    )
    return match


@transaction.atomic
def pair_next_swiss_round(stage, admin):
    """Create the next Swiss round from the current standings, avoiding rematches."""
    if stage.format != Stage.Format.SWISS:
        _fail(_("Only Swiss stages are paired round by round."))
    matches = list(stage.matches.select_related("home", "away", "winner"))
    if not matches:
        _fail(_("Create round 1 first."))
    current = max(m.round_number for m in matches)
    if current >= (stage.swiss_rounds or 0):
        _fail(_("All %(n)s Swiss rounds have been created.") % {"n": stage.swiss_rounds})
    unfinished = [m for m in matches if m.round_number == current and not m.is_settled
                  and m.status != Match.Status.CANCELLED]  # fmt: skip
    if unfinished:
        _fail(_("Round %(r)s still has %(n)s match(es) without a final result.") % {"r": current, "n": len(unfinished)})

    table = standings.calculate(stage, matches)
    ranked = [row.team for row in table]
    played = {frozenset((m.home_id, m.away_id)) for m in matches if m.home_id and m.away_id}
    had_bye = {m.winner_id for m in matches if m.status == Match.Status.BYE and m.winner_id}
    by_pk = {team.pk: team for team in ranked}
    pairs, bye = generators.swiss_pairings([t.pk for t in ranked], played, had_bye)

    last = [m for m in matches if m.round_number == current]
    length = None
    if last and last[0].play_from and last[0].play_by:
        length = last[0].play_by - last[0].play_from + datetime.timedelta(minutes=1)
    play_from = last[0].play_by + datetime.timedelta(minutes=1) if length else None
    play_by = play_from + length - datetime.timedelta(minutes=1) if length else None
    number = max(m.number for m in matches)
    label = f"Round {current + 1}"
    for home, away in pairs:
        number += 1
        Match.objects.create(
            stage=stage,
            number=number,
            round_number=current + 1,
            round_label=label,
            home=by_pk[home],
            away=by_pk[away],
            play_from=play_from,
            play_by=play_by,
        )
    if bye is not None:
        number += 1
        Match.objects.create(
            stage=stage,
            number=number,
            round_number=current + 1,
            round_label=label,
            home=by_pk[bye],
            away=None,
            play_from=play_from,
            play_by=play_by,
            status=Match.Status.BYE,
            winner=by_pk[bye],
        )
    record(admin, "stage.swiss_paired", f"Paired {label} of {stage}", target=stage.competition)
    return current + 1
