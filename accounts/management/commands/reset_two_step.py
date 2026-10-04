"""
Turn off someone's two-step sign-in, e.g. after they lose their phone and backup codes.

    python manage.py reset_two_step person@example.org --reason "Lost phone"

They set it up again at their next sign-in (administrators are sent there automatically).
Normally another administrator does this from the Administrators screen; this command is
for when no other administrator can sign in.
"""

from django.core.management.base import BaseCommand, CommandError

from accounts import two_factor
from accounts.models import User


class Command(BaseCommand):
    help = "Turn off someone's two-step sign-in (lost phone)."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--reason", required=True)

    def handle(self, *args, email, reason, **options):
        user = User.objects.filter(email__iexact=email.strip()).first()
        if user is None:
            raise CommandError(f"No account for {email}.")
        two_factor.turn_off(user, None, reason=f"Reset from the server command line: {reason}")
        self.stdout.write(self.style.SUCCESS(f"Two-step sign-in reset for {user.email}."))
