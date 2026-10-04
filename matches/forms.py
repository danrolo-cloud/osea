import datetime

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from competitions.models import Registration

from .models import Match, Stage

DATETIME_WIDGET = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


class StageForm(forms.ModelForm):
    class Meta:
        model = Stage
        fields = ["name", "format", "division", "order", "best_of", "swiss_rounds", "is_published"]

    def __init__(self, *args, competition, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.competition = competition
        self.fields["division"].queryset = competition.divisions.all()
        self.fields["format"].help_text = _(
            "Round robin, single and double elimination, and Swiss build their matches for you. "
            "Custom stages are filled in by hand."
        )
        if self.instance.pk and self.instance.matches.exists():
            self.fields["format"].disabled = True
            self.fields["division"].disabled = True
            self.fields["format"].help_text = _("Clear this stage's matches to change its format or division.")


class GenerateForm(forms.Form):
    first_day = forms.DateField(
        label=_("First round starts"), widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )
    days_per_round = forms.IntegerField(
        label=_("Days per round"),
        min_value=1,
        max_value=60,
        initial=7,
        help_text=_("Each round's play-by date is this many days after it starts. You can change any match later."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_day"].initial = timezone.localdate() + datetime.timedelta(days=7)


class MatchForm(forms.ModelForm):
    class Meta:
        model = Match
        fields = ["home", "away", "round_number", "round_label", "play_from", "play_by", "scheduled_at"]
        widgets = {"play_from": DATETIME_WIDGET, "play_by": DATETIME_WIDGET, "scheduled_at": DATETIME_WIDGET}
        help_texts = {
            "scheduled_at": _("Usually agreed by the coaches. Set it here only to override them."),
            "home": _("Changing a team here replaces any automatic 'winner of' link for that slot."),
        }

    def __init__(self, *args, stage, **kwargs):
        super().__init__(*args, **kwargs)
        teams = stage.competition.registrations.filter(status=Registration.Status.APPROVED).order_by("team_name")
        for side in ("home", "away"):
            self.fields[side].queryset = teams
            self.fields[side].required = False
            self.fields[side].empty_label = _("Bye / to be decided")

    def clean(self):
        cleaned = super().clean()
        home, away = cleaned.get("home"), cleaned.get("away")
        if home and away and home == away:
            raise forms.ValidationError(_("A team can't play itself."))
        start, end = cleaned.get("play_from"), cleaned.get("play_by")
        if start and end and end < start:
            self.add_error("play_by", _("The play-by date must be after the start."))
        return cleaned


class ProposeTimeForm(forms.Form):
    proposed_time = forms.DateTimeField(
        label=_("Match time (Toronto time)"), widget=DATETIME_WIDGET, input_formats=["%Y-%m-%dT%H:%M"]
    )
    note = forms.CharField(label=_("Note for the other coach (optional)"), max_length=300, required=False)


class ReasonForm(forms.Form):
    reason = forms.CharField(label=_("Reason"), max_length=300)
