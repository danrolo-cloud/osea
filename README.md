# OSEA platform

The web platform for the Ontario School Esports Association: school and coach
management, competition registration, schedules, results and standings.

See [docs/PLAN.md](docs/PLAN.md) for the agreed scope, decisions and phases.

## Current status: Phase 0 (foundation)

What works:
- Sign in with email and password, sign out, change password, reset a forgotten password
  (in development, the reset email is printed to the terminal instead of sent).
- Two roles, OSEA administrator and teacher coach, each with their own dashboard.
  Permissions are checked on the server: a coach who types an admin address gets a "403 not allowed" page.
- OSEA styling (purple and neon green, Montserrat and Roboto) on desktop and phone layouts.
- A style guide page for admins showing buttons, forms, tables and messages.

Not built yet: the dashboards' panels are labelled placeholders. Schools, coaches, competitions,
registrations, schedules and results arrive in Phases 1–4.

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
python manage.py seed_demo           # fictional demo accounts (development only)
python manage.py runserver           # then open http://127.0.0.1:8000
```

Demo accounts (fictional, development only), password `osea-demo-2026`:
- `admin@example.org`: OSEA administrator
- `coach@example.org`: teacher coach

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
| `accounts/` | User accounts, sign-in, roles, permission checks |
| `core/` | Home page and dashboards |
| `templates/` | Page layouts (HTML) |
| `static/` | Stylesheet, fonts, small scripts |
| `docs/` | Plan and decisions |

## Secrets

Passwords and keys are never stored in this repository. Locally they go in `.env`
(ignored by git). On the live site they are set in the hosting provider's settings.
See `.env.example` for the full list.
