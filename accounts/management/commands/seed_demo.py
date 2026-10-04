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

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from schools.models import CoachAccess, Membership, School, SchoolBoard, SchoolYear

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

        self.stdout.write(f"{len(boards)} boards, {len(schools)} schools, {len(COACHES)} coaches, school year {year}.")
        self.stdout.write("Sign in as admin@example.org (administrator) or coach@mvdsb.example.ca (coach).")
        self.stdout.write(self.style.SUCCESS(f"Demo password for all accounts: {DEMO_PASSWORD}"))

    def _user(self, email, first, last, role, verified):
        user, created = User.objects.get_or_create(
            email=email, defaults={"first_name": first, "last_name": last, "role": role}
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.email_verified_at = timezone.now() if verified else None
            user.save()
        return user
