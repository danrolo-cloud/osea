"""
Standings, calculated from final results only.

Standings are never edited by hand. They are worked out each time from the
stage's finalized matches and its settings:

  1. Points (points for a win / loss, set per stage).
  2. The stage's tiebreakers, in the order the administrator chose. Each one
     only separates teams that are still tied, and head-to-head looks only at
     matches between the teams that are tied.
  3. OSEA's recorded decision (a rank an administrator entered for the tie).

Teams still level after all of that are marked "tied" so an administrator
can see a decision is needed.
"""

from dataclasses import dataclass, field

from .models import Match, Tiebreaker


@dataclass
class Row:
    team: object
    seed: int = 999
    decision: int | None = None
    played: int = 0
    wins: int = 0
    losses: int = 0
    byes: int = 0
    points: int = 0
    games_won: int = 0
    games_lost: int = 0
    score_for: int = 0
    score_against: int = 0
    opponents: list = field(default_factory=list)
    position: int = 0
    tied: bool = False

    @property
    def game_diff(self):
        return self.games_won - self.games_lost

    @property
    def score_diff(self):
        return self.score_for - self.score_against


def calculate(stage, matches=None, entries=None):
    """Ordered list of Rows for a stage."""
    matches = list(matches if matches is not None else stage.matches.select_related("home", "away", "winner"))
    entries = list(entries if entries is not None else stage.entries.select_related("registration"))
    rows = {e.registration_id: Row(team=e.registration, seed=e.seed, decision=e.tiebreak_rank) for e in entries}

    def row(team):
        if team.pk not in rows:  # a team added to a hand-made match without being seeded
            rows[team.pk] = Row(team=team)
        return rows[team.pk]

    head_to_head = {}  # (team pk, opponent pk) -> points earned in those meetings
    for match in matches:
        if match.status in (Match.Status.COMPLETED, Match.Status.FORFEIT) and match.home and match.away:
            home, away = row(match.home), row(match.away)
            for me, them, mine, theirs, side in (
                (home, away, match.home_games, match.away_games, 0),
                (away, home, match.away_games, match.home_games, 1),
            ):
                won = match.winner_id == me.team.pk
                gained = stage.points_win if won else stage.points_loss
                me.played += 1
                me.wins += won
                me.losses += not won
                me.points += gained
                me.games_won += mine or 0
                me.games_lost += theirs or 0
                for game in match.game_scores or []:
                    me.score_for += game[side]
                    me.score_against += game[1 - side]
                me.opponents.append(them.team.pk)
                key = (me.team.pk, them.team.pk)
                head_to_head[key] = head_to_head.get(key, 0) + gained
        elif match.status == Match.Status.BYE and match.winner and stage.bye_counts_as_win:
            lucky = row(match.winner)
            lucky.byes += 1
            lucky.wins += 1
            lucky.points += stage.points_win

    def criterion_value(name, item, group):
        if name == "points":
            return item.points
        if name == Tiebreaker.HEAD_TO_HEAD:
            others = {g.team.pk for g in group if g is not item}
            return sum(head_to_head.get((item.team.pk, other), 0) for other in others)
        if name == Tiebreaker.GAME_DIFF:
            return item.game_diff
        if name == Tiebreaker.GAMES_WON:
            return item.games_won
        if name == Tiebreaker.SCORE_DIFF:
            return item.score_diff
        if name == Tiebreaker.BUCHHOLZ:
            return sum(rows[o].points for o in item.opponents if o in rows)
        raise ValueError(name)

    def order(group, criteria):
        if len(group) <= 1:
            return group
        if not criteria:
            return decide(group)
        name, rest = criteria[0], criteria[1:]
        values = {id(item): criterion_value(name, item, group) for item in group}
        result = []
        for value in sorted(set(values.values()), reverse=True):
            result += order([item for item in group if values[id(item)] == value], rest)
        return result

    def decide(group):
        """Last step: OSEA's recorded decision. Anything still level is flagged."""
        ranks = [item.decision for item in group]
        if None not in ranks and len(set(ranks)) == len(ranks):
            return sorted(group, key=lambda item: item.decision)
        for item in group:
            item.tied = True
        return sorted(
            group, key=lambda item: (item.decision is None, item.decision or 0, item.seed, item.team.team_name.lower())
        )

    ordered = order(list(rows.values()), ["points", *stage.tiebreakers])
    for position, item in enumerate(ordered, start=1):
        item.position = position
    return ordered
