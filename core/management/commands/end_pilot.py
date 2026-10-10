"""
Delete everything from the pilot so the real launch starts empty.

    python manage.py end_pilot --confirm "DELETE PILOT DATA"

Removes every record: accounts, schools, students, competitions, results and
the activity log. Only runs while the site is still marked as a test
(OSEA_ENVIRONMENT_LABEL set), so it can never run on the live site. Download
everything first if OSEA wants to keep a record of the pilot.
"""

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

PHRASE = "DELETE PILOT DATA"


class Command(BaseCommand):
    help = "Delete all pilot data before the real launch (test sites only)."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", default="", help=f'Type exactly "{PHRASE}".')

    def handle(self, *args, confirm, **options):
        if not settings.OSEA_ENVIRONMENT_LABEL:
            raise CommandError("This site isn't marked as a test site, so its data can't be deleted this way.")
        if confirm != PHRASE:
            raise CommandError(f'Nothing deleted. To delete all pilot data, add: --confirm "{PHRASE}"')
        call_command("flush", interactive=False, verbosity=0)
        self.stdout.write(self.style.SUCCESS("All pilot data deleted."))
        self.stdout.write(
            "Next: remove OSEA_ENVIRONMENT_LABEL from the app settings and deploy, "
            "then run createsuperuser for the first administrator."
        )
