# Running the OSEA platform: routine tasks

For OSEA's volunteers. Most of this takes a few minutes a month.

## Backups

There are two layers:

1. **Automatic daily backups** by the managed database (DigitalOcean keeps the last 7 days).
   These protect against mistakes and server problems.
2. **A monthly copy kept by OSEA**, in case the hosting account itself is lost:
   - Sign in as an administrator → **Exports** → **Download everything (.zip)**.
     This is every record as spreadsheets that open in Excel or Google Sheets.
   - Save it in OSEA's shared drive (a restricted folder), named with the date.
   - Keep the last 12 monthly copies; delete older ones. **It contains student and coach
     information, so never keep it on a personal device or email it.**
   - Each download is recorded in the activity log.

For a complete database copy that can rebuild the site exactly, a technical volunteer can also
download a backup from DigitalOcean (*Databases → Backups*), or run
`pg_dump --format=custom "$DATABASE_URL" > osea-YYYY-MM-DD.dump` from a trusted computer.

## Restoring (test this once a term)

- **Undo a recent mistake:** most changes can be fixed in the site itself (the activity log shows
  what changed and the old values). Use a restore only for larger problems.
- **Restore from a daily backup:** in DigitalOcean, *Databases → Backups → Restore* creates a new
  database from the chosen day. Point the app's `DATABASE_URL` at it, deploy, and check.
  Anything entered after that backup is lost, so note the time first.
- **From a `.dump` file:** `pg_restore --clean --no-owner --dbname "$DATABASE_URL" osea-YYYY-MM-DD.dump`.

Once each term, restore the latest backup into a *test* copy (never the live one) and sign in to
confirm the data is there. Record the date you did it.

## Monthly (about 30 minutes)

- [ ] Download the monthly copy (above).
- [ ] Review and merge the update pull requests GitHub (Dependabot) opened, once the automatic
      checks pass; then deploy. Security fixes for Django should be applied within a week.
- [ ] Skim the **Activity log** for anything unexpected (e.g. exports you don't recognise).
- [ ] Check **Administrators**: everyone listed still needs access; turn off anyone who doesn't.

## Start of each school year

- [ ] **School years** → add the new year and mark it current.
- [ ] Record memberships as schools pay.
- [ ] Ask coaches to update students' grades and mark students who left as "no longer at the school".
- [ ] Remove access for coaches who have left a school (**Coaches** → the coach → Remove access).
- [ ] Review the school directory for closed or merged schools (turn them off rather than deleting).

## Common requests

| Situation | What to do |
|---|---|
| Coach forgot password | They use "Forgot your password?" on the sign-in page. |
| Coach's reset email doesn't arrive | Ask them to check junk mail; confirm their email in **Coaches**. |
| "Sign-in is paused" | Too many wrong passwords; it clears by itself after 15 minutes. |
| Administrator lost their phone | They can sign in with a backup code. Otherwise another administrator uses **Administrators → Reset two-step** (with a reason); they set it up again at next sign-in. If no administrator can sign in, a technical volunteer runs `python manage.py reset_two_step email@... --reason "Lost phone"` in the DigitalOcean console. |
| A coach leaves a school | **Coaches** → the coach → Remove access to that school (keeps their history). |
| Result entered wrongly | Open the match (**Results** or the stage page) → Correct or Reopen the result, with a reason. Brackets update automatically. |
| A school asks for its data | Use the CSV exports, filtered to that school, and send through a secure channel. |

## If you suspect an account was misused

1. **Coaches** or **Administrators** → turn the account off immediately.
2. Reset their two-step sign-in and ask them to choose a new password.
3. Review the **Activity log** filtered by that person to see what they changed; fix it.
4. If student information may have been seen by someone who shouldn't have, follow OSEA's privacy
   policy and inform the affected schools; school boards may have their own reporting duties.

## What lives where

| Item | Where |
|---|---|
| Code | GitHub, `danrolo-cloud/osea` |
| Website and database | DigitalOcean, Toronto region |
| Passwords and keys for the site | DigitalOcean app settings (encrypted), never in the code |
| Email sending | the platform account in OSEA's Google Workspace (app password in the hosting settings) |
| Monthly data copies | OSEA's shared drive (restricted folder) |
| How-tos | this file, `docs/DEPLOYMENT.md`, `README.md` |
