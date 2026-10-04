"""
Games, competitions and registrations.

Nothing about a particular game is built into the code. Administrators set
every competition's rules (dates, eligibility, team size, roster limits,
required player details) and each stage's format when they set it up.
"""

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from schools.models import GRADE_CHOICES, School, SchoolYear, Student


class Game(models.Model):
    name = models.CharField(_("name"), max_length=100, unique=True)
    gamer_tag_label = models.CharField(
        _("what the game calls a player name"),
        max_length=50,
        default="Gamer tag",
        help_text=_("Shown on roster forms, e.g. Riot ID, Epic username, Nintendo Switch name."),
    )
    rank_label = models.CharField(
        _("what the game calls a rank"), max_length=50, default="Rank", help_text=_("e.g. Rank, Competitive rank.")
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("game")

    def __str__(self):
        return self.name


class Competition(models.Model):
    class RankRequirement(models.TextChoices):
        OFF = "off", _("Don't ask")
        OPTIONAL = "optional", _("Ask, but optional")
        REQUIRED = "required", _("Required")

    class RegistrationState(models.TextChoices):
        UPCOMING = "upcoming", _("Opens soon")
        OPEN = "open", _("Open")
        CLOSED = "closed", _("Closed")

    # Basics
    school_year = models.ForeignKey(SchoolYear, verbose_name=_("school year"), on_delete=models.PROTECT)
    game = models.ForeignKey(Game, verbose_name=_("game"), on_delete=models.PROTECT, related_name="competitions")
    name = models.CharField(_("competition name"), max_length=150, help_text=_("e.g. Valorant Winter League 2027."))
    season = models.CharField(_("season"), max_length=50, blank=True, help_text=_("e.g. Winter 2027."))
    description = models.TextField(_("public description"), blank=True)
    rules_url = models.URLField(_("rules link"), blank=True, help_text=_("Link to the rulebook for coaches."))
    best_of = models.PositiveSmallIntegerField(
        _("games per match (best of)"),
        null=True,
        blank=True,
        help_text=_("Default for every stage; a stage can override it. Leave blank if it doesn't apply."),
    )

    # Dates (entered and shown in Toronto time)
    registration_opens_at = models.DateTimeField(_("registration opens"))
    registration_closes_at = models.DateTimeField(_("registration closes"))
    roster_deadline = models.DateTimeField(
        _("roster deadline"),
        help_text=_("Last moment coaches can request roster changes. Must be on or after registration closes."),
    )

    # Eligibility
    allowed_levels = ArrayField(
        models.CharField(max_length=20, choices=School.Level.choices),
        verbose_name=_("school levels that can enter"),
        default=list,
    )
    min_grade = models.PositiveSmallIntegerField(_("lowest grade"), choices=GRADE_CHOICES)
    max_grade = models.PositiveSmallIntegerField(_("highest grade"), choices=GRADE_CHOICES)

    # Teams and rosters
    players_per_team = models.PositiveSmallIntegerField(
        _("players in a match"), help_text=_("How many play at once, e.g. 5 for Valorant, 1 for singles.")
    )
    roster_min = models.PositiveSmallIntegerField(_("minimum roster size"))
    roster_max = models.PositiveSmallIntegerField(_("maximum roster size"), help_text=_("Including substitutes."))
    max_teams = models.PositiveSmallIntegerField(
        _("maximum teams in the competition"), null=True, blank=True, help_text=_("Leave blank for no limit.")
    )
    max_teams_per_school = models.PositiveSmallIntegerField(
        _("maximum teams per school"), null=True, blank=True, help_text=_("Leave blank for no limit.")
    )

    # Player details collected
    require_gamer_tag = models.BooleanField(_("require each player's in-game name"), default=True)
    rank_requirement = models.CharField(
        _("ask for each player's rank"), max_length=10, choices=RankRequirement.choices, default=RankRequirement.OFF
    )

    # Visibility
    is_published = models.BooleanField(
        _("published"), default=False, help_text=_("Coaches and the public can only see published competitions.")
    )
    show_teams_publicly = models.BooleanField(_("show approved team and school names publicly"), default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-registration_opens_at", "name"]
        verbose_name = _("competition")

    def __str__(self):
        return self.name

    def clean(self):
        errors = {}
        if self.roster_min is not None and self.roster_max is not None and self.roster_min > self.roster_max:
            errors["roster_max"] = _("The maximum roster size can't be smaller than the minimum.")
        if self.players_per_team and self.roster_min is not None and self.roster_min < self.players_per_team:
            errors["roster_min"] = _("The minimum roster must be at least the number of players in a match.")
        if self.min_grade and self.max_grade and self.min_grade > self.max_grade:
            errors["max_grade"] = _("The highest grade can't be lower than the lowest grade.")
        if not self.allowed_levels:
            errors["allowed_levels"] = _("Choose at least one school level.")
        opens, closes, deadline = self.registration_opens_at, self.registration_closes_at, self.roster_deadline
        if opens and closes and closes <= opens:
            errors["registration_closes_at"] = _("Registration must close after it opens.")
        if closes and deadline and deadline < closes:
            errors["roster_deadline"] = _("The roster deadline can't be before registration closes.")
        if errors:
            raise ValidationError(errors)

    # ----- registration window -----

    def registration_state(self, now=None):
        now = now or timezone.now()
        if now < self.registration_opens_at:
            return self.RegistrationState.UPCOMING
        if now < self.registration_closes_at:
            return self.RegistrationState.OPEN
        return self.RegistrationState.CLOSED

    @property
    def registration_is_open(self):
        return self.registration_state() == self.RegistrationState.OPEN

    @property
    def roster_changes_allowed(self):
        return timezone.now() < self.roster_deadline

    # ----- eligibility -----

    def school_is_eligible(self, school):
        return school.is_active and school.level in self.allowed_levels

    def grade_is_eligible(self, grade):
        return self.min_grade <= grade <= self.max_grade

    @property
    def grade_range_label(self):
        if self.min_grade == self.max_grade:
            return _("Grade %(g)s") % {"g": self.min_grade}
        return _("Grades %(a)s–%(b)s") % {"a": self.min_grade, "b": self.max_grade}

    @property
    def asks_for_rank(self):
        return self.rank_requirement != self.RankRequirement.OFF

    def allowed_levels_display(self):
        labels = dict(School.Level.choices)
        return ", ".join(str(labels[level]) for level in self.allowed_levels if level in labels)


class Division(models.Model):
    """A group of teams within a competition. Defined by administrators for each competition."""

    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name="divisions")
    name = models.CharField(_("name"), max_length=100, help_text=_("e.g. Bronze–Gold, Middle School."))
    description = models.CharField(_("description"), max_length=255, blank=True)
    order = models.PositiveSmallIntegerField(_("display order"), default=0)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = _("division")
        constraints = [models.UniqueConstraint(fields=["competition", "name"], name="unique_division_name")]

    def __str__(self):
        return self.name


class Registration(models.Model):
    """One team entered by one school in one competition, with its roster."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SUBMITTED = "submitted", _("Submitted")
        CHANGES_REQUESTED = "changes_requested", _("Changes requested")
        APPROVED = "approved", _("Approved")
        WAITLISTED = "waitlisted", _("Waitlisted")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    competition = models.ForeignKey(Competition, on_delete=models.PROTECT, related_name="registrations")
    school = models.ForeignKey(School, on_delete=models.PROTECT, related_name="registrations")
    team_name = models.CharField(_("team name"), max_length=60, help_text=_("Shown publicly once approved."))
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    division = models.ForeignKey(
        Division,
        verbose_name=_("division"),
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="registrations",
    )
    admin_message = models.TextField(_("message from OSEA"), blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    consent_confirmed_at = models.DateTimeField(null=True, blank=True)
    consent_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["competition", "team_name"]
        verbose_name = _("registration")
        constraints = [
            models.UniqueConstraint(Lower("team_name"), "competition", name="unique_team_name_per_competition"),
        ]

    def __str__(self):
        return f"{self.team_name} ({self.school.name})"

    @property
    def is_active(self):
        return self.status != self.Status.WITHDRAWN


class RosterEntry(models.Model):
    registration = models.ForeignKey(Registration, on_delete=models.CASCADE, related_name="roster")
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="roster_entries")
    gamer_tag = models.CharField(_("in-game name"), max_length=60, blank=True)
    rank = models.CharField(_("rank"), max_length=40, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["student__first_name", "student__last_initial"]
        verbose_name = _("roster entry")
        verbose_name_plural = _("roster entries")
        constraints = [models.UniqueConstraint(fields=["registration", "student"], name="student_once_per_roster")]

    def __str__(self):
        return f"{self.student} on {self.registration.team_name}"


class RosterChange(models.Model):
    """
    A coach's request to change an approved roster before the roster deadline.

    Add a player (player_in only), remove one (player_out only), or swap one
    for another (both). An administrator approves or declines each request.
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for approval")
        APPROVED = "approved", _("Approved")
        DECLINED = "declined", _("Declined")

    registration = models.ForeignKey(Registration, on_delete=models.CASCADE, related_name="roster_changes")
    player_in = models.ForeignKey(
        Student, verbose_name=_("player to add"), null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    player_out = models.ForeignKey(
        Student, verbose_name=_("player to remove"), null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    gamer_tag = models.CharField(_("in-game name of the player being added"), max_length=60, blank=True)
    rank = models.CharField(_("rank of the player being added"), max_length=40, blank=True)
    reason = models.CharField(_("reason"), max_length=300)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decision_note = models.CharField(_("message to the coach"), max_length=300, blank=True)

    class Meta:
        ordering = ["-requested_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(player_in__isnull=False) | Q(player_out__isnull=False), name="change_names_a_player"
            ),
        ]

    def __str__(self):
        return f"{self.description} ({self.registration.team_name})"

    @property
    def description(self):
        if self.player_in and self.player_out:
            return _("Replace %(out)s with %(in)s") % {"out": self.player_out, "in": self.player_in}
        if self.player_in:
            return _("Add %(in)s") % {"in": self.player_in}
        return _("Remove %(out)s") % {"out": self.player_out}


class Announcement(models.Model):
    """A message from OSEA to a competition's coaches, optionally one division only, optionally public."""

    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name="announcements")
    division = models.ForeignKey(
        Division,
        verbose_name=_("division"),
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="announcements",
        help_text=_("Leave blank to send to the whole competition."),
    )
    title = models.CharField(_("title"), max_length=150)
    body = models.TextField(_("message"), help_text=_("Links are clickable."))
    is_public = models.BooleanField(
        _("also show on the public competition page"),
        default=False,
        help_text=_("Leave off for coach-only messages."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("announcement")

    def __str__(self):
        return self.title
