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
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from competitions.models import Competition, Division, Registration


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
        if self.status == self.Status.CANCELLED:
            return self.State.CANCELLED
        if self.status == self.Status.BYE:
            return self.State.BYE
        if self.home_id is None or self.away_id is None:
            return self.State.WAITING
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
        """Decided, so its winner and loser are known (only byes until results arrive in Phase 4)."""
        return self.status == self.Status.BYE

    @property
    def loser(self):
        return None  # a bye has no loser; results add real losers in Phase 4

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
