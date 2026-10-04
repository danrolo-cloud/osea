# OSEA platform: plan and decisions

Last updated: 2026-10-04 (Phase 2 complete)

## Goal

One place where OSEA runs competitions and teacher coaches manage their
school's participation. The platform **goes live in January 2027**. The first
title to open registration after launch is **Valorant**, but which titles run,
and when, is decided by administrators inside the app, not built into the code.

First complete workflow:

> Admin creates a competition → coach registers a school team and roster →
> admin approves and assigns a division → admin publishes fixtures →
> coach submits a result → result is confirmed or reviewed → standings update.

## Roles

| Role | Can do |
|---|---|
| OSEA administrator | Manage schools, coaches, competitions, registrations, divisions, schedules, results, announcements. |
| Teacher coach | Manage teams and students for schools they are **approved** for; register; view schedules; submit and confirm results. |
| Public visitor (no account) | See published schedules, standings, school and team names only. |

- Coach permissions belong to the **school**: any approved coach at a school can manage all its teams.
- A "competition staff" role (results/schedules without membership/finance access) may come later.
- No student accounts.

## Operating decisions (agreed defaults, 2026-10-04)

1. **Coach verification.** Coaches sign up and request a school. An OSEA admin approves each request by hand.
   Warning signs (e.g. a non-board email domain) are shown to the admin but never auto-approve.
   No school data is visible until approved.
2. **Student data.** First name, last initial, gamer tag, grade, and optional game rank.
   The coach confirms school consent forms are on file (recorded with who and when); forms are not uploaded.
   Gamer tags are not public in v1. Data hosted in Canada.
3. **Administrators set every competition's rules when they set it up** (decided 2026-10-04): registration and
   roster dates, eligible school levels and grade range, players per match, roster minimum and maximum, team
   limits (overall and per school), format and match length (best of N), which player details are required
   (in-game name, rank), and public visibility. Games are records admins create, with their own label for a
   player's in-game name (e.g. "Riot ID"). Nothing game-specific is built into the code. Standings points and
   tiebreaker order will be added to the same settings in Phase 4.
4. **Result confirmation.** The opposing coach confirms or disputes within 48 hours. No response sends it to the
   admin queue with one-click finalize (no automatic finalization). Disputes always go to an admin.
   Admins can enter or correct any result, and every change is logged.
5. **Membership.** Coaches may register while membership is pending; an admin cannot approve a registration until
   the school's membership is confirmed or a recorded exception is made. Fees are recorded by hand.

6. **Registration windows are per competition.** Admins set each competition's own registration opening and closing
   dates (and roster deadline); nothing is fixed platform-wide. Example: Super Smash Bros. Ultimate registration
   opens 2026-10-08 and closes 2026-10-27. Rules differ by title too: Smash rosters may be a single player, Rocket League 3–5.

7. **Go-live and first title.** Live in January 2027. Valorant is the first title to open registration after launch;
   administrators create it (and every later title) in the app.
8. **Language.** English at launch. All screen text is marked for translation from Phase 1 onward, so French can be
   added later by supplying translations, without reworking screens.

Registration statuses: draft → submitted → (changes requested → submitted) → approved / waitlisted; withdrawn at any point.

## Brand

- Official logos are in `docs/brand/` (full-colour bilingual "OSEA | AOSES", and white with "Play. Learn. Grow.").
- OSEA deep purple `#462a66` and the logo gradient `#312a5e` → `#952180` are sampled from the official logo.
- Neon green `#39ff14` is a stand-in until OSEA supplies an official code. It is never used as text on white
  (fails contrast); it appears on dark purple or as a button fill with dark text.
- Headings Montserrat, body Roboto. All text colour pairs checked against WCAG AA.

## Deferred (not in the first release)

Automated payments, Discord, game APIs, advanced brackets, sponsorships, student accounts,
judged/submission formats (Minecraft Education), custom registration questions per competition,
automatic round-robin generation, result screenshot uploads, notification emails beyond account emails.

## Technology (plain language)

- **Django** (Python web framework): handles sign-in, security, forms and the database for us.
  Includes a built-in back-office screen for fixing records. Version 5.2 is supported with security fixes to April 2028.
- **PostgreSQL**: the database. A widely used, free, reliable choice.
- **Server-built pages** with small touches of interactivity (htmx). No separate front-end app to maintain.
- **Hosting (to be approved before any deployment):** a Canadian-region managed host, estimated US$25–45/month
  including the database and its automatic daily backups.

## Phases

| Phase | Outcome | Target |
|---|---|---|
| 0. Foundation | Sign-in, roles, server-side permission checks, brand styling, tests running on GitHub | ✅ Oct 4 |
| 1. Schools & coaches | School directory, coach sign-up and approval, yearly membership, activity log, CSV export | ✅ Oct 4 |
| 2. Competitions & registration | Admin-managed games and competitions (own dates and rules), divisions, team registration with rosters, review queue, division assignment | ✅ Oct 4 |
| 3. Schedules & announcements | Fixtures, publishing, reschedule/forfeit/cancel/bye, coach "next match", public schedule, announcements | mid-Nov |
| 4. Results & standings | Submit, confirm or dispute, admin finalize, standings with tiebreakers, public standings | early Dec |
| 5. Pilot readiness | Hosting set up (with approval), admin two-factor sign-in, backup guide, pilot with a few coaches | before Dec 18 |
| Launch | Real coaches onboarded; Valorant registration opens | January 2027 |

Targets assume regular review checkpoints with OSEA. The December pilot must finish before the winter break.

## Phase 1 notes

- Coach sign-up requires a confirmed email address before an admin can approve access. Confirmation links are
  signed, expire after three days, and stop working if the address changes.
- Coaches who type a school that isn't in the directory are held until an admin adds the school and links it.
- The activity log is permanent: the app refuses edits and deletions, and a database rule blocks bulk changes too.
- Exports are CSV files; cells that a spreadsheet would treat as formulas are neutralised, and every download is logged.
- New administrator accounts are created in the back office (`/back-office/`) or with
  `python manage.py createsuperuser` for now; an admin-management screen can come later.

## Phase 2 notes

- Registration statuses and who can change what:
  - **Draft:** the coach edits freely while registration is open. OSEA doesn't see drafts in its review queue.
  - **Submitted:** locked; the coach can take it back to draft while registration is open.
  - **Changes requested:** the coach edits and resubmits until the roster deadline.
  - **Approved:** roster changes (add, remove or swap) only by request, approved by an admin, until the roster
    deadline.
  - **Waitlisted / withdrawn:** set by admins; coaches can withdraw their own team at any time.
- Approval requires: a roster within the competition's limits, every player eligible (grade, still at the school,
  required details filled in, not on another team in the same competition), the coach's consent confirmation,
  the school's membership confirmed or excepted for that school year, and room under the team limit.
- Rank is shown to admins for judgment only. Teams are never placed in a division automatically.
- Students are stored once per school (first name, last initial, grade) and reused across competitions.
  In-game names and ranks are stored per roster, because they differ by game.
- Public pages show competition details, and approved team and school names only if the admin turns on
  "show teams publicly". Students, rosters and coach contacts are never public.
