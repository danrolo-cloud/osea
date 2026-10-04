"""
Build the list of matches for each format.

These functions only work with lists of teams (in seed order, best first)
and return plain match plans. They don't touch the database, which keeps
them easy to test. services.generate_stage() turns the plans into matches.

A plan is a dict:
    key            unique id within the plan, used for "winner of" links
    round          round number within its bracket (1, 2, ...)
    window         which play window (1, 2, ...) the match belongs to
    label          round name shown to people ("Week 2", "Semifinal", ...)
    bracket        "", "winners", "losers" or "final"
    home, away     a team, or None (an empty slot means a bye)
    home_from, away_from   (key, "winner"/"loser") when the slot is filled by an earlier match
"""

import math


def _plan(key, rnd, window, label, bracket="", home=None, away=None, home_from=None, away_from=None):
    return {
        "key": key, "round": rnd, "window": window, "label": label, "bracket": bracket,
        "home": home, "away": away, "home_from": home_from, "away_from": away_from,
    }  # fmt: skip


# ------------------------------------------------------------------ round robin


def round_robin(teams, *, twice=False):
    """
    Everyone plays everyone (the "circle" method). With an odd number of teams,
    one team has a bye each round. With twice=True, a second half repeats every
    pairing with team 1 and team 2 swapped.
    """
    if len(teams) < 2:
        raise ValueError("At least two teams are needed.")
    slots = list(teams) + ([None] if len(teams) % 2 else [])
    n = len(slots)
    rounds = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            home, away = slots[i], slots[n - 1 - i]
            if i == 0 and r % 2:  # keep the fixed team from always being "team 1"
                home, away = away, home
            pairs.append((home, away))
        rounds.append(pairs)
        slots = [slots[0], slots[-1], *slots[1:-1]]
    if twice:
        rounds += [[(away, home) for home, away in pairs] for pairs in rounds]

    plans = []
    for r, pairs in enumerate(rounds, start=1):
        for i, (home, away) in enumerate(pairs):
            if home is None:  # put the team with the bye in the first slot
                home, away = away, None
            plans.append(_plan(f"r{r}m{i}", r, r, f"Round {r}", home=home, away=away))
    return plans


# ------------------------------------------------------------------ elimination brackets


def seeding_positions(size):
    """Standard bracket order, so seeds 1 and 2 can only meet in the final: 8 -> [1, 8, 4, 5, 2, 7, 3, 6]."""
    order = [1]
    while len(order) < size:
        total = len(order) * 2 + 1
        order = [x for seed in order for x in (seed, total - seed)]
    return order


def _bracket_size(count):
    return 2 ** math.ceil(math.log2(count))


def _elimination_label(matches_in_round):
    return {1: "Final", 2: "Semifinal", 4: "Quarterfinal"}.get(matches_in_round, f"Round of {matches_in_round * 2}")


def _winners_bracket(teams, bracket):
    """Rounds of a single-elimination bracket. Top seeds get the byes when the field isn't a power of 2."""
    size = _bracket_size(len(teams))
    order = seeding_positions(size)
    seeded = {seed: team for seed, team in enumerate(teams, start=1)}
    prefix = "w" if bracket else "m"
    rounds = []
    first = []
    for i in range(size // 2):
        first.append(
            _plan(
                f"{prefix}1-{i}",
                1,
                1,
                _elimination_label(size // 2),
                bracket,
                home=seeded.get(order[2 * i]),
                away=seeded.get(order[2 * i + 1]),
            )
        )
    rounds.append(first)
    r = 1
    while len(rounds[-1]) > 1:
        r += 1
        previous = rounds[-1]
        count = len(previous) // 2
        rounds.append(
            [
                _plan(
                    f"{prefix}{r}-{i}",
                    r,
                    r,
                    _elimination_label(count),
                    bracket,
                    home_from=(previous[2 * i]["key"], "winner"),
                    away_from=(previous[2 * i + 1]["key"], "winner"),
                )
                for i in range(count)
            ]
        )
    return rounds


def single_elimination(teams):
    if len(teams) < 2:
        raise ValueError("At least two teams are needed.")
    return [plan for rnd in _winners_bracket(teams, "") for plan in rnd]


def double_elimination(teams):
    """
    Winners bracket, losers bracket and a grand final. A team is out after two
    losses. Losers from each winners round drop into the losers bracket.
    Byes are handled automatically: an empty slot sends the other team through.
    """
    if len(teams) < 3:
        raise ValueError("At least three teams are needed for double elimination.")
    wb = _winners_bracket(teams, "winners")
    for rnd in wb:
        for plan in rnd:
            plan["label"] = "Winners " + plan["label"].lower()
    plans = [plan for rnd in wb for plan in rnd]

    # Losers round 1: losers of winners round 1 play each other.
    losers_round = 1
    window = 2
    first = wb[0]
    current = [
        _plan(
            f"l1-{i}",
            1,
            window,
            "Losers round 1",
            "losers",
            home_from=(first[2 * i]["key"], "loser"),
            away_from=(first[2 * i + 1]["key"], "loser"),
        )
        for i in range(len(first) // 2)
    ]
    plans += current

    for wb_round in wb[1:]:
        # Drop-in round: losers bracket survivors meet the teams just knocked out of the winners bracket.
        # The order is reversed to make immediate rematches less likely.
        losers_round += 1
        window += 1
        dropped = list(reversed(wb_round))
        current = [
            _plan(
                f"l{losers_round}-{i}",
                losers_round,
                window,
                f"Losers round {losers_round}",
                "losers",
                home_from=(current[i]["key"], "winner"),
                away_from=(dropped[i]["key"], "loser"),
            )
            for i in range(len(current))
        ]
        plans += current
        if len(current) > 1:
            losers_round += 1
            window += 1
            current = [
                _plan(
                    f"l{losers_round}-{i}",
                    losers_round,
                    window,
                    f"Losers round {losers_round}",
                    "losers",
                    home_from=(current[2 * i]["key"], "winner"),
                    away_from=(current[2 * i + 1]["key"], "winner"),
                )
                for i in range(len(current) // 2)
            ]
            plans += current

    plans.append(
        _plan(
            "gf",
            1,
            window + 1,
            "Grand final",
            "final",
            home_from=(wb[-1][0]["key"], "winner"),
            away_from=(current[0]["key"], "winner"),
        )
    )
    return plans


# ------------------------------------------------------------------ Swiss


def swiss_first_round(teams):
    """
    Round 1 of a Swiss stage: the top half of the seeds plays the bottom half
    (1 v 5, 2 v 6, ... with 8 teams). With an odd number, the lowest seed has a bye.
    Later rounds pair teams with the same record, so they need results (Phase 4).
    """
    if len(teams) < 2:
        raise ValueError("At least two teams are needed.")
    teams = list(teams)
    plans = []
    if len(teams) % 2:
        plans.append(_plan("s1-bye", 1, 1, "Round 1", home=teams.pop(), away=None))
    half = len(teams) // 2
    for i in range(half):
        plans.insert(i, _plan(f"s1-{i}", 1, 1, "Round 1", home=teams[i], away=teams[half + i]))
    return plans


def swiss_pairings(ranked, played, had_bye):
    """
    Pair a Swiss round from the current standings (best first).

    Teams play the highest-ranked team they haven't already met. With an odd
    number, the lowest-ranked team that hasn't had a bye gets one. If a
    rematch can't be avoided, teams are paired in standings order.
    Returns (pairs, bye_team).
    """
    teams = list(ranked)
    bye = None
    if len(teams) % 2:
        bye = next((t for t in reversed(teams) if t not in had_bye), teams[-1])
        teams.remove(bye)

    def pair(remaining):
        if not remaining:
            return []
        first = remaining[0]
        for i in range(1, len(remaining)):
            if frozenset((first, remaining[i])) not in played:
                rest = pair(remaining[1:i] + remaining[i + 1 :])
                if rest is not None:
                    return [(first, remaining[i]), *rest]
        return None

    pairs = pair(teams)
    if pairs is None:
        pairs = [(teams[i], teams[i + 1]) for i in range(0, len(teams), 2)]
    return pairs, bye
