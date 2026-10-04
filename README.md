# OSEA platform

The web platform for the Ontario School Esports Association: school and coach
management, competition registration, schedules, results and standings.

See [docs/PLAN.md](docs/PLAN.md) for the agreed scope, decisions and phases.

## Current status: Phase 5 in progress (pilot readiness). The full competition workflow works

What works, with real data in the database:
- **Coach sign-up:** account plus school request in one form, email confirmation link, "request another school".
- **Coach approval:** admins review requests with warning flags (unconfirmed email, email from outside the school's
  board, school not in the directory), then approve or decline with a message that is emailed to the coach.
  Admins can remove access or turn off an account later.
- **Permissions:** coaches only see schools they're approved for; this is checked on the server for every page.
- **School directory:** boards (with staff email domains), schools, school years, and yearly membership with
  payment recorded by hand. Exceptions require a reason.
- **Dashboards:** admin dashboard lists coach requests and schools needing membership follow-up; coach dashboard
  shows access status, approved schools and membership.
- **Activity log** of every important change (who, when, before and after), which can't be edited or deleted.
- **CSV exports** of schools, coaches and memberships.

Phase 2 adds, with real data in the database:
- **Games and competitions** set up entirely by admins: dates, eligibility (school levels, grades), team size,
  roster limits, team limits, format, required player details, publishing.
- **Divisions** defined per competition; admins place teams (rank is shown, never used automatically).
- **Coach registration:** start a team, add students (on file or new), submit with consent confirmation,
  reopen while registration is open, withdraw; roster change requests (add/remove/swap) after approval.
- **Admin review:** approve, waitlist or ask for changes, with automatic checks (eligibility, roster limits,
  membership, capacity) and emails to the school's coaches; direct roster edits; team and roster CSV exports.
- **Students list** per school, private to that school's coaches and OSEA.
- **Public competition pages** with approved team and school names only (when the admin allows it).

Phase 3 adds:
- **Stages** with a format chosen by admins: round robin, double round robin, single or double elimination,
  Swiss, or custom. Matches are generated from the admin's seeding, with byes and play windows; brackets show
  "winner of match N" until earlier matches are decided.
- **Coach-to-coach scheduling:** one coach proposes a time, the other accepts; reschedule the same way.
  Admins can set times, add or edit matches, cancel and restore.
- **My matches** for coaches, schedules and brackets on public competition pages (published stages only).
- **Announcements** for a competition or division, optionally public.

Phase 4 adds:
- **Results:** a coach reports games won (optionally each game's score); the other team confirms or disputes.
  Disputes and results unconfirmed after 48 hours go to the admin **Results** queue (one click to make final).
  Admins can enter, correct, reopen or record a forfeit for any match.
- **Brackets advance automatically**, including the double-elimination grand-final reset; **Swiss rounds** are
  paired from the standings, avoiding rematches.
- **Standings** per stage from final results only, with admin-chosen points and tiebreaker order and a recorded
  OSEA decision for complete ties; shown publicly for published stages.

Phase 5 so far:
- **Two-step sign-in** with an authenticator app and one-time backup codes; required for administrators
  (including the back office), optional for coaches.
- **Sign-in protection:** pauses after repeated wrong passwords or codes; limits on sign-ups, password resets
  and confirmation emails.
- **Administrators screen:** add administrators (they set their own password), turn accounts off, reset a
  colleague's two-step sign-in.
- **Download everything:** every record as spreadsheets in one zip, for OSEA's monthly off-site copy.
- **Security headers** (content security policy) and an automated accessibility check (axe) with no issues.
- **Deployment template and guides:** `docs/DEPLOYMENT.md`, `docs/OPERATIONS.md`, `.do/app.yaml`.

Not done yet, and needing OSEA's approval: hosting, real email sending, the domain. Emails print to the
terminal in development; nothing is sent.

## Running it on your computer

You need Python 3.11+ and PostgreSQL 14+.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                 # local settings; never commit .env

# Create a local database (once)
createuser osea --pwprompt           # use the password "osea", or change DATABASE_URL in .env
createdb osea --owner osea

python manage.py migrate             # set up the database tables
python manage.py createcachetable    # small table used for sign-in attempt limits
python manage.py seed_demo           # fictional boards, schools and coaches (development only)
python manage.py runserver           # then open http://127.0.0.1:8000
```

Demo accounts (fictional, development only), password `osea-demo-2026`:
- `admin@example.org`: OSEA administrator
- `coach@mvdsb.example.ca`: teacher coach (approved at one school, pending at another)

To create the first real administrator: `python manage.py createsuperuser`. Add others from the
**Administrators** screen. Two-step sign-in is optional locally (`OSEA_REQUIRE_ADMIN_2FA=false` in `.env`)
and always required on the live site.

## Checks

```bash
python manage.py test          # automated tests
ruff check . && ruff format --check .   # code style
```

Both run automatically on GitHub for every push.

## Where things live

| Folder | Contents |
|---|---|
| `config/` | Site-wide settings and web addresses |
| `accounts/` | User accounts, sign-in, sign-up, email confirmation, roles |
| `schools/` | School boards, schools, school years, memberships, coach access and approval |
| `competitions/` | Games, competitions, divisions, registrations, rosters and their rules (`services.py`) |
| `matches/` | Stages, formats (`generators.py`), matches, scheduling rules (`services.py`) |
| `audit/` | The activity log |
| `core/` | Home page, dashboards, CSV export helper |
| `templates/` | Page layouts (HTML) |
| `static/` | Stylesheet, fonts, small scripts |
| `docs/` | Plan and decisions (`PLAN.md`), going online (`DEPLOYMENT.md`), routine tasks and backups (`OPERATIONS.md`) |

## Secrets

Passwords and keys are never stored in this repository. Locally they go in `.env`
(ignored by git). On the live site they are set in the hosting provider's settings.
See `.env.example` for the full list.
