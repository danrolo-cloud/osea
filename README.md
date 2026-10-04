# OSEA platform

The web platform for the Ontario School Esports Association: school and coach
management, competition registration, schedules, results and standings.

See [docs/PLAN.md](docs/PLAN.md) for the agreed scope, decisions and phases.

## Current status: Phase 1 (schools and coaches)

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

Not built yet: competitions, registrations, rosters, schedules, results (Phases 2–4). Those dashboard panels are
labelled "coming in later phases". Emails print to the terminal in development; nothing is sent.

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
python manage.py seed_demo           # fictional boards, schools and coaches (development only)
python manage.py runserver           # then open http://127.0.0.1:8000
```

Demo accounts (fictional, development only), password `osea-demo-2026`:
- `admin@example.org`: OSEA administrator
- `coach@mvdsb.example.ca`: teacher coach (approved at one school, pending at another)

To create a real administrator account: `python manage.py createsuperuser`.

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
| `audit/` | The activity log |
| `core/` | Home page, dashboards, CSV export helper |
| `templates/` | Page layouts (HTML) |
| `static/` | Stylesheet, fonts, small scripts |
| `docs/` | Plan and decisions |

## Secrets

Passwords and keys are never stored in this repository. Locally they go in `.env`
(ignored by git). On the live site they are set in the hosting provider's settings.
See `.env.example` for the full list.
