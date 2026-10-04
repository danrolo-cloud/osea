from django import forms
from django.utils.translation import gettext_lazy as _

from .models import CoachAccess, Membership, School, SchoolBoard, SchoolYear


class SchoolChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, school):
        board = school.board.name if school.board else _("Independent")
        return f"{school.name}, {school.city} ({board})"


class SchoolAccessRequestForm(forms.Form):
    """Used at sign-up and when an existing coach asks to coach at another school."""

    school = SchoolChoiceField(
        label=_("Your school"),
        queryset=School.objects.filter(is_active=True).select_related("board"),
        required=False,
        empty_label=_("Choose your school…"),
    )
    requested_school_name = forms.CharField(
        label=_("School not in the list?"),
        required=False,
        max_length=300,
        help_text=_("Enter the school name, city and school board. OSEA will add it."),
    )
    position = forms.CharField(
        label=_("Your role at the school"),
        max_length=200,
        help_text=_("For example: Grade 10 Computer Studies teacher."),
    )
    attestation = forms.BooleanField(
        label=_(
            "I am a teacher or staff member at this school and will be responsible for its esports "
            "teams, students and communication with OSEA."
        ),
    )

    def __init__(self, *args, coach=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.coach = coach

    def clean(self):
        cleaned = super().clean()
        school = cleaned.get("school")
        other = (cleaned.get("requested_school_name") or "").strip()
        if not school and not other:
            self.add_error("school", _("Choose your school, or type its name below if it isn't listed."))
        elif school and other:
            self.add_error("requested_school_name", _("Choose a school from the list or type one, not both."))
        elif school and self.coach is not None:
            existing = CoachAccess.objects.filter(coach=self.coach, school=school).first()
            if existing:
                self.add_error(
                    "school",
                    _("You already have a request for this school (%(status)s).")
                    % {"status": existing.get_status_display().lower()},
                )
        cleaned["requested_school_name"] = other
        return cleaned

    def save(self, coach):
        return CoachAccess.objects.create(
            coach=coach,
            school=self.cleaned_data["school"],
            requested_school_name=self.cleaned_data["requested_school_name"] if not self.cleaned_data["school"] else "",
            position=self.cleaned_data["position"],
        )


# ---------- Administrator forms ----------


class SchoolForm(forms.ModelForm):
    class Meta:
        model = School
        fields = ["name", "city", "board", "level", "is_active", "admin_notes"]
        widgets = {"admin_notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["board"].queryset = SchoolBoard.objects.filter(is_active=True) | SchoolBoard.objects.filter(
            pk=getattr(self.instance, "board_id", None)
        )


class SchoolBoardForm(forms.ModelForm):
    class Meta:
        model = SchoolBoard
        fields = ["name", "email_domains", "is_active"]
        widgets = {"email_domains": forms.Textarea(attrs={"rows": 3})}


class SchoolYearForm(forms.ModelForm):
    # Not a model field here: the view moves the "current" marker between years
    # itself, because the database allows only one current year at a time.
    make_current = forms.BooleanField(
        label=_("This is the current school year"),
        required=False,
        help_text=_("Dashboards and membership checks use the current school year."),
    )

    class Meta:
        model = SchoolYear
        fields = ["name", "start_date", "end_date"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "end_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }


class MembershipForm(forms.ModelForm):
    class Meta:
        model = Membership
        fields = ["status", "amount", "paid_on", "reference", "notes"]
        widgets = {
            "paid_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class AccessDecisionForm(forms.Form):
    """Approve, decline or remove a coach's access."""

    school = SchoolChoiceField(
        label=_("Link to school"),
        queryset=School.objects.filter(is_active=True).select_related("board"),
        required=False,
        help_text=_("Needed when the coach typed a school that wasn't in the directory."),
    )
    decision_note = forms.CharField(
        label=_("Message to the coach"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("Shown to the coach and included in their email. Required when declining or removing access."),
    )
