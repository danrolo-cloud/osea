"""
Create fictional demo accounts for development and demonstrations.

    python manage.py seed_demo

Refuses to run unless DJANGO_DEBUG is on, so demo logins can never be
created on the live site. Safe to run more than once.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User

DEMO_PASSWORD = "osea-demo-2026"

DEMO_USERS = [
    {"email": "admin@example.org", "first_name": "Avery", "last_name": "Admin", "role": User.Role.ADMIN},
    {"email": "coach@example.org", "first_name": "Jordan", "last_name": "Coach", "role": User.Role.COACH},
]


class Command(BaseCommand):
    help = "Create fictional demo accounts (development only)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs in development (DJANGO_DEBUG=true).")

        for data in DEMO_USERS:
            user, created = User.objects.get_or_create(
                email=data["email"],
                defaults={k: v for k, v in data.items() if k != "email"},
            )
            user.set_password(DEMO_PASSWORD)
            user.save()
            verb = "Created" if created else "Reset"
            self.stdout.write(f"{verb} {user.get_role_display().lower()}: {user.email}")

        self.stdout.write(self.style.SUCCESS(f"Demo password for all accounts: {DEMO_PASSWORD}"))
