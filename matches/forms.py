import datetime

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from competitions.models import Registration

from .models import Match, Stage, Tiebreaker, default_tiebreakers

DATETIME_WIDGET = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


TIEBREAKER_SLOTS = 5


class StageForm(forms.ModelForm):
    class Meta:
        model = Stage
        fields = [
            "name", "format", "division", "order", "best_of", "swiss_rounds", "is_published",
            "points_win", "points_loss", "bye_counts_as_win", "grand_final_reset",
        ]  # fmt: skip

    def __init__(self, *args, competition, **kwargs):
        super().__init__(*args, **kwargs)
        # Tiebreakers are chosen in order with one drop-down per position (checkboxes can't express order).
        current = list(self.instance.tiebreakers or []) if self.instance.pk else list(default_tiebreakers())
        for i in range(TIEBREAKER_SLOTS):
            self.fields[f"tiebreaker_{i + 1}"] = forms.ChoiceField(
                label=_("Tiebreaker %(n)s") % {"n": i + 1},
                choices=[("", _("— none —"))] + list(Tiebreaker.choices),
                required=False,
                initial=current[i] if i < len(current) else "",
            )
        self.instance.competition = competition
        self.fields["division"].queryset = competition.divisions.all()
        self.fields["format"].help_text = _(
            "Round robin, single and double elimination, and Swiss build their matches for you. "
            "Custom stages are filled in by hand."
        )
        self.tiebreaker_fields = [self[f"tiebreaker_{i + 1}"] for i in range(TIEBREAKER_SLOTS)]
        if self.instance.pk and self.instance.matches.exists():
            self.fields["format"].disabled = True
            self.fields["division"].disabled = True
            self.fields["format"].help_text = _("Clear this stage's matches to change its format or division.")

    def clean(self):
        cleaned = super().clean()
        chosen = [cleaned.get(f"tiebreaker_{i + 1}") for i in range(TIEBREAKER_SLOTS)]
        chosen = [c for c in chosen if c]
        if len(chosen) != len(set(chosen)):
            raise forms.ValidationError(_("Each tiebreaker can only be used once."))
        self.instance.tiebreakers = chosen
        return cleaned


class ResultForm(forms.Form):
    home_games = forms.IntegerField(min_value=0, max_value=99)
    away_games = forms.IntegerField(min_value=0, max_value=99)
    game_scores = forms.CharField(
        label=_("Each game's score (optional)"),
        required=False,
        max_length=200,
        help_text=_("Team 1's score first, e.g. 13-11, 9-13, 13-7. Used for the score-difference tiebreaker."),
    )
    note = forms.CharField(label=_("Note (optional)"), required=False, max_length=300)

    def __init__(self, *args, match, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["home_games"].label = _("Games won by %(team)s") % {"team": match.home_label}
        self.fields["away_games"].label = _("Games won by %(team)s") % {"team": match.away_label}


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
