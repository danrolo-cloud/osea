# OSEA platform: plan and decisions

Last updated: 2026-10-04 (Phase 5 in progress)

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
   tiebreaker order will be added in Phase 4.
9. **Formats are chosen by administrators, per stage** (decided 2026-10-04). A competition has one or more stages
   (e.g. Swiss, then playoffs). Each stage's format: round robin, double round robin, single elimination,
   double elimination, Swiss, or custom (matches added by hand).
10. **Coaches schedule their own matches** (decided 2026-10-04). One team's coach proposes a time, the other team's
    coach accepts, and the time is set; no administrator approval. Either side can propose a change later; the
    agreed time stands until a new one is accepted. Administrators can still set, change or cancel any match.
11. **Announcements** are posted to a whole competition or one division, shown on those coaches' dashboards, and on
    the public competition page only if marked public. They will be emailed once real email is approved.
12. **Results and standings** (defaults agreed 2026-10-04, may change later; all are per-stage settings):
    a result records games won by each side, with optional per-game scores; either coach reports it, the other
    confirms (final) or disputes; disputes and results unconfirmed after 48 hours go to OSEA. Standings use points
    for a win/loss and the admin's ordered tiebreakers (head-to-head, game difference, games won, score
    difference, opponents' points), then OSEA's recorded decision. Double elimination plays a grand-final reset
    if the losers-bracket team wins the grand final (can be switched off per stage).
13. **Email is sent through OSEA's Google Workspace** (decided 2026-10-04): a dedicated platform account
    (e.g. `platform@`), free under Workspace for Nonprofits; replies forward to OSEA's main inbox.
14. **Hosting plan: DigitalOcean, Toronto** (recommended 2026-10-04, awaiting OSEA approval): US$5/month app
    plus ~US$15/month managed database with daily backups. OSEA is an incorporated nonprofit, not a
    registered charity, so Microsoft's charity credits don't apply; DigitalOcean's nonprofit credits may.
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
| 3. Schedules & announcements | Stages with admin-chosen formats, generated matches and brackets, coach-to-coach scheduling, cancellations and byes, public schedules, announcements | ✅ Oct 4 |
| 4. Results & standings | Submit, confirm or dispute, admin finalize, forfeits, bracket advancement, Swiss pairing, standings with tiebreakers, public standings | ✅ Oct 4 |
| 5. Pilot readiness | Done: two-step sign-in, sign-in limits, admin accounts, full export, security headers, accessibility check, deployment and operations guides. Email: OSEA's Google Workspace. Waiting on OSEA: hosting account, domain; then a pilot with a few coaches | before Dec 18 |
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

## Phase 3 notes

- Match generation from the admin's seeding:
  - Round robin uses the standard "circle" method; odd numbers give one bye per round.
  - Elimination brackets use standard seeding, so seeds 1 and 2 can only meet in the final, and byes go to the
    top seeds. Double elimination includes the losers bracket and a grand final.
  - Swiss creates round 1 (top half v bottom half); later rounds need results, so they come in Phase 4.
- Each round has a play window (start date + days per round), entered in Toronto time; admins can change any match.
- Bracket matches are linked ("winner of match 5", "loser of match 2"). Byes already move teams forward;
  results will move winners and losers forward in Phase 4.
- Coaches see opposing coaches' names and email addresses only on a match their teams play against each other,
  so they can arrange times directly. This is never shown publicly.
- Stages are hidden from coaches and the public until an admin publishes them.
- Not yet: forfeits (recorded with results in Phase 4), grand-final bracket reset, automatic Swiss pairing
  after round 1, and match-time reminder emails.

## Phase 4 notes

- Only final results count. A coach's report stays "waiting for confirmation" until the other team confirms or an
  administrator makes it final.
- No draws: every match needs a winner. In a best of N, the winner takes exactly N÷2+1 games (e.g. 2–0 or 2–1).
- A forfeit is recorded by an administrator and scores as N÷2+1 games to 0 for the other team.
- Brackets: winners and losers move on as soon as a result is final. A result that a later match depends on
  can't be changed until that later result is reopened; reopening clears the team that moved on.
- Swiss: the next round is paired from the standings once the current round is finished, avoiding rematches;
  the bye goes to the lowest-ranked team that hasn't had one. Byes count as wins only if the stage says so.
- Standings are never typed in; they are recalculated from final results every time. Teams still level after
  every tiebreaker are marked and wait for OSEA's recorded decision.

The first complete workflow now works end to end: an administrator creates a competition, a coach registers a
team and roster, the administrator approves it and places it in a division, publishes the matches, coaches agree
times and report results, results are confirmed or reviewed, and standings update.

## Phase 5 notes

- Two-step sign-in uses the standard authenticator-app codes (TOTP); each code works once. Ten one-time
  backup codes are shown once and stored only as hashes. Required for administrators on the live site,
  including the back office, which now uses the main sign-in page.
- Attempt limits: 5 wrong passwords per account or 20 per network address in 15 minutes pauses sign-in for
  15 minutes; 5 wrong codes likewise; password reset emails at most 3 per address per hour (the page never
  reveals whether an account exists); 5 sign-ups per network address per hour.
- The full export holds personal information; it is administrator-only and every download is logged.
- Accessibility: axe (WCAG 2.1 A/AA and best practices) on 30+ page views at desktop and phone sizes: no
  issues. Keyboard: skip link first, visible focus, sign-in works with the keyboard alone.
- Still to do once OSEA approves: create the hosting, email and DNS settings (docs/DEPLOYMENT.md), a test
  copy of the site for the pilot, and a short privacy notice for coaches and schools (OSEA to approve the wording).
