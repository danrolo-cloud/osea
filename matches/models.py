"""
Stages, matches and match-time proposals.

A competition is played in one or more stages (e.g. "Regular season", then
"Playoffs"). Administrators choose each stage's format. Matches in bracket
formats can be fed by earlier matches ("winner of match 3"), so later rounds
fill in automatically as earlier ones are decided.

Match times are agreed between the two teams' coaches: one proposes a time,
the other accepts. Administrators can set or change a time at any point.
"""

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from competitions.models import Competition, Division, Registration


class Tiebreaker(models.TextChoices):
    HEAD_TO_HEAD = "head_to_head", _("Head-to-head (results between the tied teams)")
    GAME_DIFF = "game_diff", _("Game difference (games won minus games lost)")
    GAMES_WON = "games_won", _("Games won")
    SCORE_DIFF = "score_diff", _("Score difference (e.g. rounds or goals, from per-game scores)")
    BUCHHOLZ = "buchholz", _("Opponents' points (Buchholz, for Swiss)")


def default_tiebreakers():
    return [Tiebreaker.HEAD_TO_HEAD, Tiebreaker.GAME_DIFF, Tiebreaker.SCORE_DIFF]


class Stage(models.Model):
    class Format(models.TextChoices):
        ROUND_ROBIN = "round_robin", _("Round robin (everyone plays everyone once)")
        DOUBLE_ROUND_ROBIN = "double_round_robin", _("Double round robin (everyone plays everyone twice)")
        SINGLE_ELIMINATION = "single_elim", _("Single elimination")
        DOUBLE_ELIMINATION = "double_elim", _("Double elimination")
        SWISS = "swiss", _("Swiss")
        CUSTOM = "custom", _("Custom (matches added by hand)")

    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name="stages")
    name = models.CharField(_("stage name"), max_length=100, help_text=_("e.g. Regular season, Playoffs."))
    format = models.CharField(_("format"), max_length=20, choices=Format.choices)
    division = models.ForeignKey(
        Division,
        verbose_name=_("division"),
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="stages",
        help_text=_("Leave blank to include approved teams from every division."),
    )
    order = models.PositiveSmallIntegerField(_("display order"), default=0)
    best_of = models.PositiveSmallIntegerField(
        _("games per match (best of)"), null=True, blank=True, help_text=_("Leave blank to use the competition's.")
    )
    swiss_rounds = models.PositiveSmallIntegerField(
        _("number of Swiss rounds"), null=True, blank=True, help_text=_("Only for Swiss stages.")
    )
    is_published = models.BooleanField(
        _("published"),
        default=False,
        help_text=_("Coaches and the public see this stage's matches only once it's published."),
    )

    # Standings (round robin, Swiss and custom stages)
    points_win = models.PositiveSmallIntegerField(_("points for a win"), default=1)
    points_loss = models.PositiveSmallIntegerField(_("points for a loss"), default=0)
    tiebreakers = ArrayField(
        models.CharField(max_length=20, choices=Tiebreaker.choices),
        verbose_name=_("tiebreakers, in order"),
        default=default_tiebreakers,
        blank=True,
        help_text=_("Used in this order when teams have the same points. A recorded OSEA decision always comes last."),
    )
    bye_counts_as_win = models.BooleanField(
        _("a bye counts as a win"), default=False, help_text=_("Usual in Swiss; not usual in round robin.")
    )
    grand_final_reset = models.BooleanField(
        _("grand final reset"),
        default=True,
        help_text=_("Double elimination: if the losers-bracket team wins the grand final, a second final is played."),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["competition", "order", "pk"]
        verbose_name = _("stage")

    def __str__(self):
        return f"{self.competition.name}: {self.name}"

    def clean(self):
        if self.format == self.Format.SWISS and not self.swiss_rounds:
            raise ValidationError({"swiss_rounds": _("Enter how many Swiss rounds will be played.")})
        if self.division_id and self.competition_id and self.division.competition_id != self.competition_id:
            raise ValidationError({"division": _("That division belongs to another competition.")})

    @property
    def has_standings(self):
        return not self.is_bracket

    @property
    def games_to_win(self):
        """Games needed to win a match: 2 in a best of 3. 1 if no best-of is set."""
        best_of = self.effective_best_of
        return best_of // 2 + 1 if best_of else 1

    @property
    def is_bracket(self):
        return self.format in (self.Format.SINGLE_ELIMINATION, self.Format.DOUBLE_ELIMINATION)

    @property
    def effective_best_of(self):
        return self.best_of or self.competition.best_of

    def eligible_teams(self):
        """Approved teams that belong in this stage."""
        teams = self.competition.registrations.filter(status=Registration.Status.APPROVED).select_related("school")
        if self.division_id:
            teams = teams.filter(division_id=self.division_id)
        return teams.order_by("team_name")


class StageTeam(models.Model):
    """A team's place in a stage, with its seed (1 = top seed)."""

    stage = models.ForeignKey(Stage, on_delete=models.CASCADE, related_name="entries")
    registration = models.ForeignKey(Registration, on_delete=models.PROTECT, related_name="stage_entries")
    seed = models.PositiveSmallIntegerField()
    tiebreak_rank = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=_("OSEA's recorded decision for a tie that no tiebreaker separates (1 = higher)."),
    )

    class Meta:
        ordering = ["stage", "seed"]
        constraints = [
            models.UniqueConstraint(fields=["stage", "registration"], name="team_once_per_stage"),
            models.UniqueConstraint(fields=["stage", "seed"], name="unique_seed_per_stage"),
        ]

    def __str__(self):
        return f"{self.seed}. {self.registration.team_name}"


class Match(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        BYE = "bye", _("Bye")
        CANCELLED = "cancelled", _("Cancelled")
        COMPLETED = "completed", _("Completed")
        FORFEIT = "forfeit", _("Forfeit")

    class Bracket(models.TextChoices):
        NONE = "", _("—")
        WINNERS = "winners", _("Winners bracket")
        LOSERS = "losers", _("Losers bracket")
        FINAL = "final", _("Grand final")

    class Outcome(models.TextChoices):
        WINNER = "winner", _("Winner")
        LOSER = "loser", _("Loser")

    class State(models.TextChoices):
        """What a coach or visitor needs to know about a match right now (worked out, not stored)."""

        WAITING = "waiting", _("Waiting for earlier results")
        TO_SCHEDULE = "to_schedule", _("To be scheduled")
        SCHEDULED = "scheduled", _("Scheduled")
        BYE = "bye", _("Bye")
        CANCELLED = "cancelled", _("Cancelled")
        RESULT_PENDING = "result_pending", _("Result waiting for confirmation")
        DISPUTED = "disputed", _("Result disputed")
        FINAL = "final", _("Final")

    stage = models.ForeignKey(Stage, on_delete=models.CASCADE, related_name="matches")
    number = models.PositiveIntegerField(_("match number"), help_text=_("Unique within the stage."))
    round_number = models.PositiveSmallIntegerField(_("round"), default=1)
    round_label = models.CharField(_("round name"), max_length=60, blank=True, help_text=_("e.g. Week 3, Semifinal."))
    bracket = models.CharField(max_length=10, choices=Bracket.choices, blank=True, default="")

    home = models.ForeignKey(
        Registration, verbose_name=_("team 1"), null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    away = models.ForeignKey(
        Registration, verbose_name=_("team 2"), null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    home_source = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    home_source_outcome = models.CharField(max_length=10, choices=Outcome.choices, blank=True)
    away_source = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    away_source_outcome = models.CharField(max_length=10, choices=Outcome.choices, blank=True)

    play_from = models.DateTimeField(_("play from"), null=True, blank=True)
    play_by = models.DateTimeField(_("play by"), null=True, blank=True, help_text=_("Deadline for this match."))
    scheduled_at = models.DateTimeField(_("match time"), null=True, blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    winner = models.ForeignKey(Registration, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    home_games = models.PositiveSmallIntegerField(null=True, blank=True)
    away_games = models.PositiveSmallIntegerField(null=True, blank=True)
    game_scores = models.JSONField(
        default=list, blank=True, help_text=_("Optional per-game scores, e.g. [[13, 11], [9, 13], [13, 7]].")
    )
    finalized_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    is_reset = models.BooleanField(default=False, help_text=_("A grand-final reset match."))
    cancel_reason = models.CharField(_("reason"), max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["stage", "round_number", "bracket", "number"]
        verbose_name = _("match")
        verbose_name_plural = _("matches")
        constraints = [
            models.UniqueConstraint(fields=["stage", "number"], name="unique_match_number_per_stage"),
        ]

    def __str__(self):
        return _("Match %(n)s") % {"n": self.number}

    @property
    def state(self):
        if self.status in (self.Status.COMPLETED, self.Status.FORFEIT):
            return self.State.FINAL
        if self.status == self.Status.CANCELLED:
            return self.State.CANCELLED
        if self.status == self.Status.BYE:
            return self.State.BYE
        if self.home_id is None or self.away_id is None:
            return self.State.WAITING
        pending = getattr(self, "_pending_result", None)
        if pending is None:
            pending = (
                self.submissions.filter(status__in=["pending", "disputed"]).values_list("status", flat=True).first()
            )
        if pending == "disputed":
            return self.State.DISPUTED
        if pending == "pending":
            return self.State.RESULT_PENDING
        if self.scheduled_at:
            return self.State.SCHEDULED
        return self.State.TO_SCHEDULE

    def get_state_display(self):
        return self.State(self.state).label

    @property
    def is_playable(self):
        return self.status == self.Status.OPEN and self.home_id and self.away_id

    @property
    def is_settled(self):
        """Decided, so its winner and loser are known."""
        return self.status in (self.Status.BYE, self.Status.COMPLETED, self.Status.FORFEIT)

    @property
    def has_result(self):
        return self.status in (self.Status.COMPLETED, self.Status.FORFEIT)

    @property
    def loser(self):
        if not self.has_result or self.winner is None:
            return None  # a bye has no loser
        return self.away if self.winner_id == self.home_id else self.home

    @property
    def score_label(self):
        if not self.has_result:
            return ""
        label = f"{self.home_games}–{self.away_games}"
        return label + (" " + str(_("(forfeit)")) if self.status == self.Status.FORFEIT else "")

    def teams(self):
        return [t for t in (self.home, self.away) if t is not None]

    def slot_label(self, side):
        """'Lynx Purple', 'Winner of match 3', 'Bye' or 'To be decided' for one side of the match."""
        team = getattr(self, side)
        if team is not None:
            return team.team_name
        source = getattr(self, f"{side}_source")
        if source is not None and not source.is_settled:
            if getattr(self, f"{side}_source_outcome") == self.Outcome.LOSER:
                return _("Loser of match %(n)s") % {"n": source.number}
            return _("Winner of match %(n)s") % {"n": source.number}
        if source is not None or self.status == self.Status.BYE:
            return _("Bye")  # fed by a bye, or this side is simply empty: nobody will play here
        return _("To be decided")

    @property
    def home_label(self):
        return self.slot_label("home")

    @property
    def away_label(self):
        return self.slot_label("away")


class TimeProposal(models.Model):
    """One team's coach suggests a match time; the other team's coach accepts or declines."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for the other team")
        ACCEPTED = "accepted", _("Accepted")
        DECLINED = "declined", _("Declined")
        WITHDRAWN = "withdrawn", _("Withdrawn")
        REPLACED = "replaced", _("Replaced by a newer proposal")

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="proposals")
    proposed_time = models.DateTimeField(_("proposed time"))
    proposing_team = models.ForeignKey(Registration, on_delete=models.PROTECT, related_name="+")
    proposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    note = models.CharField(_("note"), max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    response_note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.match}: {self.proposed_time}"


class ResultSubmission(models.Model):
    """
    A coach reports a match result. The other team's coaches confirm it (it
    becomes final) or dispute it (OSEA decides). Unanswered after 48 hours,
    it goes to OSEA's queue.
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for the other team to confirm")
        CONFIRMED = "confirmed", _("Confirmed")
        DISPUTED = "disputed", _("Disputed")
        REPLACED = "replaced", _("Replaced")
        ACCEPTED_BY_OSEA = "osea", _("Finalized by OSEA")
        REJECTED_BY_OSEA = "rejected", _("Set aside by OSEA")

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="submissions")
    submitting_team = models.ForeignKey(Registration, on_delete=models.PROTECT, related_name="+")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    home_games = models.PositiveSmallIntegerField()
    away_games = models.PositiveSmallIntegerField()
    game_scores = models.JSONField(default=list, blank=True)
    note = models.CharField(_("note"), max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    dispute_reason = models.CharField(_("what's wrong"), max_length=500, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.match}: {self.home_games}–{self.away_games}"

    @property
    def winner(self):
        return self.match.home if self.home_games > self.away_games else self.match.away
