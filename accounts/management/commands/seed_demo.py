"""
Create fictional demo data for development and demonstrations.

    python manage.py seed_demo

Every board, school and person here is made up, and all email domains use
the reserved ".example" names that can never belong to a real organisation.
Refuses to run unless DJANGO_DEBUG is on, so demo data can never reach the
live site. Safe to run more than once.
"""

import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from competitions.models import Competition, Division, Game, Registration, RosterEntry
from schools.models import CoachAccess, Membership, School, SchoolBoard, SchoolYear, Student

DEMO_PASSWORD = "osea-demo-2026"

BOARDS = [
    ("Maple Valley District School Board", "mvdsb.example.ca"),
    ("Lakeshore Catholic District School Board", "lcdsb.example.ca"),
    ("Conseil scolaire Rivière-Nord", "csrn.example.ca"),
]

# (name, city, board index or None, level)
SCHOOLS = [
    ("Maplewood Secondary School", "Maple Valley", 0, School.Level.SECONDARY),
    ("Cedar Ridge High School", "Cedar Falls", 0, School.Level.SECONDARY),
    ("Birchview Public School", "Maple Valley", 0, School.Level.ELEMENTARY),
    ("St. Brigid Catholic Secondary School", "Port Aldwin", 1, School.Level.SECONDARY),
    ("Harbour Lights Catholic Elementary School", "Port Aldwin", 1, School.Level.ELEMENTARY),
    ("École secondaire Les Érables", "Northbrook", 2, School.Level.SECONDARY),
    ("Northgate Academy", "Elmsworth", None, School.Level.COMBINED),
]

# (school index, status, amount, notes)
MEMBERSHIPS = [
    (0, Membership.Status.CONFIRMED, Decimal("150.00"), ""),
    (1, Membership.Status.PENDING, None, "Invoice sent Sept. 15."),
    (3, Membership.Status.CONFIRMED, Decimal("150.00"), ""),
    (4, Membership.Status.CONFIRMED, Decimal("100.00"), ""),
    (5, Membership.Status.EXEMPT, None, "First-year pilot school; fee waived by the board of directors."),
]

# (email, first, last, verified, [(school index or unlisted name, status, position)])
COACHES = [
    (
        "coach@mvdsb.example.ca",
        "Jordan",
        "Rivera",
        True,
        [
            (0, CoachAccess.Status.APPROVED, "Computer Studies teacher"),
            (2, CoachAccess.Status.PENDING, "Esports club supervisor"),
        ],
    ),
    ("priya.shah@mvdsb.example.ca", "Priya", "Shah", True, [(0, CoachAccess.Status.APPROVED, "Math teacher")]),
    ("sam.lee@lcdsb.example.ca", "Sam", "Lee", True, [(3, CoachAccess.Status.PENDING, "Technology teacher")]),
    ("alex.morgan@mail.example.com", "Alex", "Morgan", True, [(1, CoachAccess.Status.PENDING, "Parent volunteer")]),
    (
        "taylor.nguyen@mvdsb.example.ca",
        "Taylor",
        "Nguyen",
        False,
        [
            ("Riverside Middle School, Elmsworth (Maple Valley DSB)", CoachAccess.Status.PENDING, "Grade 8 teacher"),
        ],
    ),
    ("marie.tremblay@csrn.example.ca", "Marie", "Tremblay", True, [(5, CoachAccess.Status.APPROVED, "Enseignante")]),
    ("chris.patel@lcdsb.example.ca", "Chris", "Patel", True, [(4, CoachAccess.Status.APPROVED, "Grade 6 teacher")]),
]


class Command(BaseCommand):
    help = "Create fictional demo data (development only)."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs in development (DJANGO_DEBUG=true).")

        admin = self._user("admin@example.org", "Avery", "Admin", User.Role.ADMIN, verified=True)

        boards = [
            SchoolBoard.objects.get_or_create(name=name, defaults={"email_domains": domain})[0]
            for name, domain in BOARDS
        ]
        schools = [
            School.objects.get_or_create(
                name=name, city=city, defaults={"board": boards[b] if b is not None else None, "level": level}
            )[0]
            for name, city, b, level in SCHOOLS
        ]

        SchoolYear.objects.get_or_create(
            name="2025–26", defaults={"start_date": datetime.date(2025, 9, 1), "end_date": datetime.date(2026, 6, 30)}
        )
        year, _ = SchoolYear.objects.get_or_create(
            name="2026–27", defaults={"start_date": datetime.date(2026, 9, 1), "end_date": datetime.date(2027, 6, 30)}
        )
        if not year.is_current:
            SchoolYear.objects.filter(is_current=True).update(is_current=False)
            year.is_current = True
            year.save()

        for index, status, amount, notes in MEMBERSHIPS:
            Membership.objects.get_or_create(
                school=schools[index],
                school_year=year,
                defaults={
                    "status": status,
                    "amount": amount,
                    "paid_on": datetime.date(2026, 9, 20) if amount else None,
                    "reference": f"ETR-{1000 + index}" if amount else "",
                    "notes": notes,
                    "updated_by": admin,
                },
            )

        for email, first, last, verified, requests in COACHES:
            coach = self._user(email, first, last, User.Role.COACH, verified=verified)
            for school_ref, status, position in requests:
                lookup = (
                    {"school": schools[school_ref]}
                    if isinstance(school_ref, int)
                    else {"school": None, "requested_school_name": school_ref}
                )
                decided = status != CoachAccess.Status.PENDING
                CoachAccess.objects.get_or_create(
                    coach=coach,
                    **lookup,
                    defaults={
                        "status": status,
                        "position": position,
                        "decided_at": timezone.now() if decided else None,
                        "decided_by": admin if decided else None,
                    },
                )

        self._competitions(year, schools, admin)

        self.stdout.write(f"{len(boards)} boards, {len(schools)} schools, {len(COACHES)} coaches, school year {year}.")
        self.stdout.write(
            "3 competitions: Valorant (opens Jan. 5), Smash singles (Oct. 8-27), Rocket League demo (open now)."
        )
        self.stdout.write("Sign in as admin@example.org (administrator) or coach@mvdsb.example.ca (coach).")
        self.stdout.write(self.style.SUCCESS(f"Demo password for all accounts: {DEMO_PASSWORD}"))

    def _competitions(self, year, schools, admin):
        toronto = ZoneInfo("America/Toronto")
        valorant = Game.objects.get_or_create(name="Valorant", defaults={"gamer_tag_label": "Riot ID"})[0]
        smash = Game.objects.get_or_create(
            name="Super Smash Bros. Ultimate", defaults={"gamer_tag_label": "Nintendo Switch name"}
        )[0]
        rocket = Game.objects.get_or_create(name="Rocket League", defaults={"gamer_tag_label": "Epic username"})[0]

        def at(y, m, d, hh=9, mm=0):
            return datetime.datetime(y, m, d, hh, mm, tzinfo=toronto)

        Competition.objects.get_or_create(
            name="Valorant Winter League 2027",
            defaults=dict(
                school_year=year,
                game=valorant,
                season="Winter 2027",
                format=Competition.Format.LEAGUE,
                best_of=3,
                description="Five-a-side league for secondary schools. Weekly matches, playoffs in March.",
                registration_opens_at=at(2027, 1, 5),
                registration_closes_at=at(2027, 1, 22, 23, 59),
                roster_deadline=at(2027, 2, 5, 23, 59),
                allowed_levels=[School.Level.SECONDARY, School.Level.COMBINED],
                min_grade=9,
                max_grade=12,
                players_per_team=5,
                roster_min=5,
                roster_max=7,
                max_teams_per_school=2,
                require_gamer_tag=True,
                rank_requirement=Competition.RankRequirement.OPTIONAL,
                is_published=True,
            ),
        )
        Competition.objects.get_or_create(
            name="Smash Bros. Fall Singles 2026",
            defaults=dict(
                school_year=year,
                game=smash,
                season="Fall 2026",
                format=Competition.Format.BRACKET,
                best_of=3,
                description="One-on-one bracket. Each school may enter up to four players.",
                registration_opens_at=at(2026, 10, 8),
                registration_closes_at=at(2026, 10, 27, 23, 59),
                roster_deadline=at(2026, 10, 27, 23, 59),
                allowed_levels=[School.Level.ELEMENTARY, School.Level.SECONDARY, School.Level.COMBINED],
                min_grade=6,
                max_grade=12,
                players_per_team=1,
                roster_min=1,
                roster_max=1,
                max_teams_per_school=4,
                require_gamer_tag=True,
                rank_requirement=Competition.RankRequirement.OFF,
                is_published=True,
            ),
        )
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        rl, created = Competition.objects.get_or_create(
            name="Rocket League Demo League (fictional)",
            defaults=dict(
                school_year=year,
                game=rocket,
                season="Demo",
                format=Competition.Format.LEAGUE,
                best_of=5,
                description="A made-up competition with registration open now, for trying the platform.",
                registration_opens_at=now - datetime.timedelta(days=3),
                registration_closes_at=now + datetime.timedelta(days=14),
                roster_deadline=now + datetime.timedelta(days=28),
                allowed_levels=[School.Level.ELEMENTARY, School.Level.SECONDARY, School.Level.COMBINED],
                min_grade=7,
                max_grade=12,
                players_per_team=3,
                roster_min=3,
                roster_max=5,
                max_teams_per_school=2,
                require_gamer_tag=True,
                rank_requirement=Competition.RankRequirement.REQUIRED,
                is_published=True,
                show_teams_publicly=True,
            ),
        )
        if not created:
            return
        divisions = {
            name: Division.objects.create(competition=rl, name=name, order=i)
            for i, name in enumerate(["Middle School", "Bronze–Gold", "Platinum–Diamond", "Champion+"])
        }

        def students(school, names, grades):
            return [
                Student.objects.get_or_create(
                    school=school, first_name=first, last_initial=initial, defaults={"grade": grade}
                )[0]
                for (first, initial), grade in zip(names, grades, strict=True)
            ]

        maplewood = students(
            schools[0],
            [("Avery", "K"), ("Jun", "P"), ("Mira", "S"), ("Theo", "B"), ("Lena", "D"), ("Omar", "F"), ("Ivy", "R")],
            [9, 10, 11, 12, 10, 11, 9],
        )
        harbour = students(schools[4], [("Noah", "T"), ("Ella", "W"), ("Sam", "C"), ("Ruby", "L")], [7, 8, 8, 7])
        erables = students(schools[5], [("Léa", "G"), ("Mathis", "R"), ("Chloé", "B"), ("Hugo", "L")], [10, 11, 12, 9])
        ranks = ["Gold II", "Platinum I", "Diamond III", "Champion I", "Silver III", "Gold I", "Platinum III"]

        def team(school, name, roster, status, creator, division=None):
            registration = Registration.objects.create(
                competition=rl, school=school, team_name=name, created_by=creator, status=status, division=division
            )
            for i, student in enumerate(roster):
                RosterEntry.objects.create(
                    registration=registration,
                    student=student,
                    gamer_tag=f"{student.first_name}_{i}rl",
                    rank=ranks[i % len(ranks)],
                )
            if status != Registration.Status.DRAFT:
                registration.submitted_at = registration.consent_confirmed_at = now - datetime.timedelta(days=1)
                registration.submitted_by = registration.consent_confirmed_by = creator
            if status == Registration.Status.APPROVED:
                registration.decided_at, registration.decided_by = now, admin
            registration.save()

        jordan = User.objects.get(email="coach@mvdsb.example.ca")
        team(schools[0], "Maplewood Lynx Purple", maplewood[:4], Registration.Status.SUBMITTED, jordan)
        team(schools[0], "Maplewood Lynx Green", maplewood[4:6], Registration.Status.DRAFT, jordan)
        team(
            schools[4],
            "Harbour Hawks",
            harbour,
            Registration.Status.APPROVED,
            User.objects.get(email="chris.patel@lcdsb.example.ca"),
            divisions["Middle School"],
        )
        team(
            schools[5],
            "Les Érables Esports",
            erables[:3],
            Registration.Status.APPROVED,
            User.objects.get(email="marie.tremblay@csrn.example.ca"),
            divisions["Platinum–Diamond"],
        )

    def _user(self, email, first, last, role, verified):
        user, created = User.objects.get_or_create(
            email=email, defaults={"first_name": first, "last_name": last, "role": role}
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.email_verified_at = timezone.now() if verified else None
            user.save()
        return user
