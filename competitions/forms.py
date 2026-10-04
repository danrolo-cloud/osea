from django import forms
from django.utils.translation import gettext_lazy as _

from schools.models import GRADE_CHOICES, School, SchoolYear, Student

from .models import Announcement, Competition, Division, Game

DATETIME_WIDGET = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


class GameForm(forms.ModelForm):
    class Meta:
        model = Game
        fields = ["name", "gamer_tag_label", "rank_label", "is_active"]


class CompetitionForm(forms.ModelForm):
    allowed_levels = forms.MultipleChoiceField(
        label=_("School levels that can enter"),
        choices=School.Level.choices,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Competition
        fields = [
            "name", "game", "school_year", "season", "description", "rules_url", "best_of",
            "registration_opens_at", "registration_closes_at", "roster_deadline",
            "allowed_levels", "min_grade", "max_grade",
            "players_per_team", "roster_min", "roster_max", "max_teams", "max_teams_per_school",
            "require_gamer_tag", "rank_requirement",
            "is_published", "show_teams_publicly",
        ]  # fmt: skip
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "registration_opens_at": DATETIME_WIDGET,
            "registration_closes_at": DATETIME_WIDGET,
            "roster_deadline": DATETIME_WIDGET,
        }
        help_texts = {
            "registration_opens_at": _("Toronto time."),
            "registration_closes_at": _("Toronto time."),
        }

    # Groups of fields, shown as separate sections on the setup page.
    sections = [
        (_("Basics"), ["name", "game", "school_year", "season", "description", "rules_url", "best_of"]),
        (_("Dates"), ["registration_opens_at", "registration_closes_at", "roster_deadline"]),
        (_("Who can enter"), ["allowed_levels", "min_grade", "max_grade"]),
        (_("Teams and rosters"), ["players_per_team", "roster_min", "roster_max", "max_teams", "max_teams_per_school"]),
        (_("Player details to collect"), ["require_gamer_tag", "rank_requirement"]),
        (_("Visibility"), ["is_published", "show_teams_publicly"]),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_game = getattr(self.instance, "game_id", None)
        self.fields["game"].queryset = Game.objects.filter(is_active=True) | Game.objects.filter(pk=current_game)
        self.fields["school_year"].queryset = SchoolYear.objects.all()
        if not self.instance.pk:
            self.fields["school_year"].initial = SchoolYear.current()

    def section_fields(self):
        return [(title, [self[name] for name in names]) for title, names in self.sections]


class DivisionForm(forms.ModelForm):
    class Meta:
        model = Division
        fields = ["name", "description", "order"]


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = ["first_name", "last_initial", "grade", "is_active"]
        help_texts = {"last_initial": _("Only the first letter of the last name is stored.")}


class RegistrationStartForm(forms.Form):
    school = forms.ModelChoiceField(label=_("School"), queryset=School.objects.none())
    team_name = forms.CharField(label=_("Team name"), max_length=60, help_text=_("Shown publicly once approved."))

    def __init__(self, *args, schools=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["school"].queryset = schools if schools is not None else School.objects.none()
        if schools is not None and schools.count() == 1:
            self.fields["school"].initial = schools.first()


class TeamNameForm(forms.Form):
    team_name = forms.CharField(label=_("Team name"), max_length=60)


class AddPlayerForm(forms.Form):
    """Add a student who is already on file, or a new one, to a roster in one step."""

    student = forms.ModelChoiceField(
        label=_("Student already on file"),
        queryset=Student.objects.none(),
        required=False,
        empty_label=_("Choose a student…"),
    )
    first_name = forms.CharField(label=_("First name"), max_length=100, required=False)
    last_initial = forms.CharField(label=_("Last initial"), max_length=2, required=False)
    grade = forms.TypedChoiceField(
        label=_("Grade"), choices=[("", "—")] + GRADE_CHOICES, coerce=int, required=False, empty_value=None
    )
    gamer_tag = forms.CharField(max_length=60, required=False)
    rank = forms.CharField(max_length=40, required=False)

    def __init__(self, *args, registration, **kwargs):
        super().__init__(*args, **kwargs)
        self.registration = registration
        competition = registration.competition
        on_roster = registration.roster.values("student")
        self.fields["student"].queryset = registration.school.students.filter(is_active=True).exclude(pk__in=on_roster)
        self.fields["gamer_tag"].label = competition.game.gamer_tag_label
        self.fields["gamer_tag"].required = competition.require_gamer_tag
        self.fields["rank"].label = competition.game.rank_label
        self.fields["rank"].required = competition.rank_requirement == Competition.RankRequirement.REQUIRED
        if not competition.asks_for_rank:
            del self.fields["rank"]

    def clean(self):
        cleaned = super().clean()
        student = cleaned.get("student")
        new_fields = [cleaned.get("first_name"), cleaned.get("last_initial"), cleaned.get("grade")]
        if student and any(new_fields):
            raise forms.ValidationError(_("Choose a student on file or enter a new one, not both."))
        if not student:
            if not all(new_fields):
                raise forms.ValidationError(
                    _("Choose a student on file, or enter a new student's first name, last initial and grade.")
                )
        return cleaned

    def get_or_create_student(self, user):
        if self.cleaned_data.get("student"):
            return self.cleaned_data["student"]
        return Student.objects.create(
            school=self.registration.school,
            first_name=self.cleaned_data["first_name"],
            last_initial=self.cleaned_data["last_initial"],
            grade=self.cleaned_data["grade"],
            created_by=user,
        )


class SubmitForm(forms.Form):
    consent = forms.BooleanField(
        label=_(
            "I confirm that our school has the required consent forms on file for every player on this roster, "
            "and that the information above is correct."
        ),
    )


class RosterChangeForm(forms.Form):
    player_out = forms.ModelChoiceField(
        label=_("Player to remove"), queryset=Student.objects.none(), required=False, empty_label=_("No one")
    )
    player_in = forms.ModelChoiceField(
        label=_("Player to add"),
        queryset=Student.objects.none(),
        required=False,
        empty_label=_("No one"),
        help_text=_("Add the student on your school's student list first if they aren't there."),
    )
    gamer_tag = forms.CharField(max_length=60, required=False)
    rank = forms.CharField(max_length=40, required=False)
    reason = forms.CharField(label=_("Reason"), max_length=300)

    def __init__(self, *args, registration, **kwargs):
        super().__init__(*args, **kwargs)
        competition = registration.competition
        on_roster = registration.roster.values("student")
        self.fields["player_out"].queryset = Student.objects.filter(pk__in=on_roster)
        self.fields["player_in"].queryset = registration.school.students.filter(is_active=True).exclude(
            pk__in=on_roster
        )
        self.fields["gamer_tag"].label = _("%(label)s of the player being added") % {
            "label": competition.game.gamer_tag_label
        }
        self.fields["rank"].label = _("%(label)s of the player being added") % {"label": competition.game.rank_label}
        if not competition.asks_for_rank:
            del self.fields["rank"]


class RegistrationDecisionForm(forms.Form):
    division = forms.ModelChoiceField(label=_("Division"), queryset=Division.objects.none(), required=False)
    message = forms.CharField(
        label=_("Message to the coach"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("Emailed to the school's coaches. Required when asking for changes."),
    )

    def __init__(self, *args, registration, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["division"].queryset = registration.competition.divisions.all()
        self.fields["division"].initial = registration.division


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ["title", "body", "division", "is_public"]
        widgets = {"body": forms.Textarea(attrs={"rows": 6})}

    def __init__(self, *args, competition, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["division"].queryset = competition.divisions.all()
        self.fields["division"].empty_label = _("Everyone in the competition")
