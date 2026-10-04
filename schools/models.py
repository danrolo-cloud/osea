from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class SchoolBoard(models.Model):
    name = models.CharField(_("name"), max_length=200, unique=True)
    email_domains = models.TextField(
        _("staff email domains"),
        blank=True,
        help_text=_(
            "One per line, e.g. exampleboard.on.ca. Used only to flag coach requests from other "
            "addresses for a closer look; it never approves anyone automatically."
        ),
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("school board")

    def __str__(self):
        return self.name

    def domain_list(self):
        return [line.strip().lower().lstrip("@") for line in self.email_domains.splitlines() if line.strip()]

    def matches_email(self, email):
        domain = email.rsplit("@", 1)[-1].lower()
        return any(domain == d or domain.endswith("." + d) for d in self.domain_list())


class School(models.Model):
    class Level(models.TextChoices):
        ELEMENTARY = "elementary", _("Elementary")
        SECONDARY = "secondary", _("Secondary")
        COMBINED = "combined", _("Combined (elementary and secondary)")

    name = models.CharField(_("school name"), max_length=200)
    board = models.ForeignKey(
        SchoolBoard,
        verbose_name=_("school board"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="schools",
        help_text=_("Leave blank for independent schools."),
    )
    level = models.CharField(_("level"), max_length=20, choices=Level.choices)
    city = models.CharField(_("city or town"), max_length=100)
    is_active = models.BooleanField(
        _("active"), default=True, help_text=_("Turn off instead of deleting, so the school's history is kept.")
    )
    admin_notes = models.TextField(_("OSEA notes"), blank=True, help_text=_("Only OSEA administrators see this."))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("school")
        constraints = [
            models.UniqueConstraint(fields=["name", "city"], name="unique_school_name_city"),
        ]

    def __str__(self):
        return f"{self.name} ({self.city})"


class SchoolYear(models.Model):
    name = models.CharField(_("name"), max_length=20, unique=True, help_text=_("For example 2026–27."))
    start_date = models.DateField(_("start date"))
    end_date = models.DateField(_("end date"))
    is_current = models.BooleanField(
        _("current school year"),
        default=False,
        help_text=_("Dashboards and membership checks use the current school year."),
    )

    class Meta:
        ordering = ["-start_date"]
        verbose_name = _("school year")
        constraints = [
            models.UniqueConstraint(
                fields=["is_current"], condition=Q(is_current=True), name="one_current_school_year"
            ),
            models.CheckConstraint(
                condition=Q(end_date__gt=models.F("start_date")), name="school_year_ends_after_start"
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValidationError({"end_date": _("The end date must be after the start date.")})

    @classmethod
    def current(cls):
        return cls.objects.filter(is_current=True).first()


class Membership(models.Model):
    """A school's OSEA membership for one school year. Payment is recorded by hand."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        CONFIRMED = "confirmed", _("Confirmed")
        EXEMPT = "exempt", _("Exception granted")

    school = models.ForeignKey(School, on_delete=models.PROTECT, related_name="memberships")
    school_year = models.ForeignKey(
        SchoolYear, verbose_name=_("school year"), on_delete=models.PROTECT, related_name="memberships"
    )
    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.PENDING)
    amount = models.DecimalField(_("amount paid ($)"), max_digits=8, decimal_places=2, null=True, blank=True)
    paid_on = models.DateField(_("date paid"), null=True, blank=True)
    reference = models.CharField(
        _("payment reference"),
        max_length=100,
        blank=True,
        help_text=_("Cheque number, e-transfer reference or invoice number."),
    )
    notes = models.TextField(_("notes"), blank=True, help_text=_("Required when granting an exception."))
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-school_year__start_date", "school__name"]
        verbose_name = _("membership")
        constraints = [
            models.UniqueConstraint(fields=["school", "school_year"], name="one_membership_per_school_year"),
        ]

    def __str__(self):
        return f"{self.school.name}, {self.school_year}: {self.get_status_display()}"

    def clean(self):
        if self.status == self.Status.EXEMPT and not self.notes.strip():
            raise ValidationError({"notes": _("Explain why an exception is being granted.")})

    @property
    def in_good_standing(self):
        return self.status in (self.Status.CONFIRMED, self.Status.EXEMPT)


class CoachAccessQuerySet(models.QuerySet):
    def approved(self):
        return self.filter(status=CoachAccess.Status.APPROVED, coach__is_active=True, school__is_active=True)

    def pending(self):
        return self.filter(status=CoachAccess.Status.PENDING)


class CoachAccess(models.Model):
    """
    A coach's link to a school. A coach can see and manage a school's data
    only while this link is APPROVED by an OSEA administrator.
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for approval")
        APPROVED = "approved", _("Approved")
        DECLINED = "declined", _("Declined")
        REVOKED = "revoked", _("Access removed")

    coach = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="school_access")
    school = models.ForeignKey(
        School, verbose_name=_("school"), on_delete=models.PROTECT, null=True, blank=True, related_name="coach_access"
    )
    requested_school_name = models.CharField(
        _("school not in the list"),
        max_length=300,
        blank=True,
        help_text=_("School name, city and school board, if your school isn't in the list."),
    )
    position = models.CharField(
        _("your role at the school"), max_length=200, help_text=_("For example: Grade 10 Computer Studies teacher.")
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decision_note = models.TextField(
        _("message to the coach"),
        blank=True,
        help_text=_("Shown to the coach. Required when declining or removing access."),
    )

    objects = CoachAccessQuerySet.as_manager()

    class Meta:
        ordering = ["-requested_at"]
        verbose_name = _("coach access")
        verbose_name_plural = _("coach access")
        constraints = [
            models.UniqueConstraint(
                fields=["coach", "school"], condition=Q(school__isnull=False), name="one_access_per_coach_school"
            ),
            models.CheckConstraint(
                condition=Q(school__isnull=False) | ~Q(requested_school_name=""), name="access_names_a_school"
            ),
        ]

    def __str__(self):
        return f"{self.coach.get_full_name()} → {self.school_label}"

    @property
    def school_label(self):
        return str(self.school) if self.school else f"{self.requested_school_name} (not in directory)"

    def review_flags(self):
        """Things an administrator should look at before approving."""
        flags = []
        if not self.coach.email_verified_at:
            flags.append(_("Email address not verified yet."))
        if self.school is None:
            flags.append(_("School is not in the directory. Add it, then link this request to it."))
        elif (
            self.school.board
            and self.school.board.domain_list()
            and not self.school.board.matches_email(self.coach.email)
        ):
            flags.append(_("Email address is not from %(board)s.") % {"board": self.school.board.name})
        if not self.coach.is_active:
            flags.append(_("This coach's account is turned off."))
        return flags

    @property
    def can_be_approved(self):
        return self.school is not None and bool(self.coach.email_verified_at) and self.coach.is_active


GRADE_CHOICES = [(g, _("Grade %(n)s") % {"n": g}) for g in range(1, 13)]


class Student(models.Model):
    """
    A student at a school. Private: only that school's approved coaches and
    OSEA administrators can see these records. Never shown on public pages.

    Only what is needed to run competitions is stored: first name, last
    initial and grade. Game-specific details (gamer tag, rank) are stored on
    each roster entry instead, because they differ between games.
    """

    school = models.ForeignKey(School, on_delete=models.PROTECT, related_name="students")
    first_name = models.CharField(_("first name"), max_length=100)
    last_initial = models.CharField(_("last initial"), max_length=2)
    grade = models.PositiveSmallIntegerField(_("grade"), choices=GRADE_CHOICES)
    is_active = models.BooleanField(
        _("still at this school"),
        default=True,
        help_text=_("Turn off when the student leaves. Their past rosters are kept."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["first_name", "last_initial"]
        verbose_name = _("student")

    def __str__(self):
        return f"{self.first_name} {self.last_initial}."

    def save(self, *args, **kwargs):
        self.first_name = self.first_name.strip()
        self.last_initial = self.last_initial.strip().rstrip(".").upper()[:2]
        super().save(*args, **kwargs)
