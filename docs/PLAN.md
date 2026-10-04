# OSEA platform: plan and decisions

Last updated: 2026-10-04

## Goal

One place where OSEA runs competitions and teacher coaches manage their
school's participation. The first release runs **one Rocket League season**
end to end, rolling out in **January 2027**.

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
3. **Rocket League pilot rules.** 3v3, rosters of 3–5 players, best-of-5 matches, round robin within each division.
   Standings by match wins; tiebreakers: head-to-head, then game difference, then a recorded admin decision.
   A forfeit counts as a 3–0 loss.
4. **Result confirmation.** The opposing coach confirms or disputes within 48 hours. No response sends it to the
   admin queue with one-click finalize (no automatic finalization). Disputes always go to an admin.
   Admins can enter or correct any result, and every change is logged.
5. **Membership.** Coaches may register while membership is pending; an admin cannot approve a registration until
   the school's membership is confirmed or a recorded exception is made. Fees are recorded by hand.

6. **Registration windows are per competition.** Admins set each competition's own registration opening and closing
   dates (and roster deadline); nothing is fixed platform-wide. Example: Super Smash Bros. Ultimate registration
   opens 2026-10-08 and closes 2026-10-27. Rules differ by title too: Smash rosters may be a single player, Rocket League 3–5.

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
| 1. Schools & coaches | School directory, coach sign-up and approval, yearly membership, activity log, CSV export | mid-Oct |
| 2. Competitions & registration | Competition setup, divisions, team registration with rosters, review queue, division assignment | early Nov |
| 3. Schedules & announcements | Fixtures, publishing, reschedule/forfeit/cancel/bye, coach "next match", public schedule, announcements | mid-Nov |
| 4. Results & standings | Submit, confirm or dispute, admin finalize, standings with tiebreakers, public standings | early Dec |
| 5. Pilot readiness | Hosting set up (with approval), admin two-factor sign-in, backup guide, pilot with a few coaches | before Dec 18 |
| Launch | Real coaches onboarded, Rocket League season runs | January 2027 |

Targets assume regular review checkpoints with OSEA. The December pilot must finish before the winter break.
