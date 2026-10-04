# Putting the OSEA platform online

**Status: not deployed.** Nothing in this guide has been done yet. OSEA must approve
hosting and create the accounts below before anything goes online.

This guide assumes DigitalOcean's Toronto region (data stays in Canada). The
platform is a standard Django app, so another Canadian host would work with
small changes.

## What OSEA needs to set up (once)

| Account | Why | Approximate cost |
|---|---|---|
| DigitalOcean (in OSEA's name, OSEA's billing) | Runs the website and the database | US$5/month app + ~US$15/month database (about US$245/year) |
| A sending account in OSEA's Google Workspace (e.g. `platform@` your domain) | Sends sign-up, approval and match emails | free (Workspace for Nonprofits) |
| Access to OSEA's domain settings (DNS) | Points `play.osea.ca` at the platform | usually already paid for |

**Lower the cost:** DigitalOcean's *DO for Nonprofits & Social Enterprises* program gives eligible
nonprofits working on education up to US$2,500 in one-time credits (eligibility is checked by a service
called Percent; the program is open to nonprofits and social enterprises, not only registered charities). Apply right after creating the account, and
check how long the credits last before counting on them. Without credits, the costs above apply.

Use an OSEA-owned email address for these accounts (not a personal one), turn on
two-step sign-in for each, and record who has access in OSEA's records.

## Step by step

1. **Database.** In DigitalOcean, create a *Managed PostgreSQL* database, version 16,
   region **Toronto (TOR1)**, the smallest size. Daily backups are included.
2. **App.** Create an *App* from the GitHub repository `danrolo-cloud/osea`, branch `main`,
   region **Toronto**. The file `.do/app.yaml` describes every setting; DigitalOcean can import it.
   Turn **off** "deploy on push" so OSEA decides when updates go live.
3. **Settings (environment variables).** Enter these in the app's settings. Mark the secret
   ones as *Encrypted*. They are never stored in the code.

   | Setting | Value |
   |---|---|
   | `DJANGO_DEBUG` | `false` |
   | `DJANGO_SECRET_KEY` | a long random value (*Encrypted*). Generate one with `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
   | `DATABASE_URL` | filled in automatically when the database is attached |
   | `DJANGO_ALLOWED_HOSTS` | `play.osea.ca` |
   | `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://play.osea.ca` |
   | `OSEA_CLIENT_IP_HEADER` | `HTTP_DO_CONNECTING_IP` (lets sign-in limits see real visitor addresses) |
   | `DJANGO_EMAIL_BACKEND` | `django.core.mail.backends.smtp.EmailBackend` |
   | `EMAIL_HOST` | `smtp.gmail.com` |
   | `EMAIL_PORT` | `587` |
   | `EMAIL_HOST_USER` | the sending account's address, e.g. `platform@osea.ca` (*Encrypted*) |
   | `EMAIL_HOST_PASSWORD` | the sending account's **app password** from step 6, not its normal password (*Encrypted*) |
   | `DEFAULT_FROM_EMAIL` | `OSEA Esports <platform@osea.ca>` (must be the sending account's address) |

   Do **not** set `OSEA_ENVIRONMENT_LABEL` or `OSEA_REQUIRE_ADMIN_2FA` on the live site.
   (A separate *test* copy should set `OSEA_ENVIRONMENT_LABEL=Test` so nobody mistakes it for the real one.)
4. **Before each release** the app runs `python manage.py migrate` and `createcachetable`
   automatically (the "prepare-database" job), which updates the database structure.
5. **Domain: `play.osea.ca`.** OSEA's main Wix website stays exactly as it is. In DigitalOcean, open the app →
   *Settings → Domains → Add domain* → `play.osea.ca`, choose "You manage your domain", and copy the
   **CNAME** value it shows (something like `osea-platform-xxxxx.ondigitalocean.app`).

   The domain was bought through GoDaddy, but its records may be managed either at GoDaddy or at Wix.
   To find out: GoDaddy → *My Products* → osea.ca → *DNS* → **Nameservers**.
   - Nameservers are GoDaddy's (`…domaincontrol.com`): in GoDaddy's *DNS Records*, **Add New Record** →
     Type `CNAME`, Name `play`, Value = the DigitalOcean value, TTL 1 hour → Save.
   - Nameservers are Wix's (`…wixdns.net`): add it in Wix instead: *Wix dashboard → Settings → Domains →
     osea.ca → Manage DNS records → CNAME → Add record*, Host `play`, value as above.

   Only **add** this one record. Don't change the nameservers or any existing record: they keep the Wix
   site and Google Workspace email working. Back in DigitalOcean the domain shows as active once it sees
   the record, usually within an hour (up to a day), and it sets up HTTPS automatically.
   Finally, add a "Competitions & coach sign-in" link on the Wix site pointing to `https://play.osea.ca`.
   (Link to it rather than embedding it in a Wix page: the platform refuses to be shown inside other
   sites, which protects sign-in.)
6. **Email (Google Workspace).** A Workspace administrator for OSEA:
   1. Creates a user just for the platform, e.g. `platform@osea.ca`. Free under Workspace for Nonprofits.
      Give it a long password stored in OSEA's password manager, and turn on 2-Step Verification for it.
   2. Signed in as that user, creates an **app password** (Google Account → Security → 2-Step Verification →
      App passwords), named "OSEA platform". This 16-letter password goes in `EMAIL_HOST_PASSWORD` only.
   3. Sets that user's Gmail to forward incoming mail to OSEA's main inbox, because coaches will reply
      to the platform's emails.
   4. In the Google Admin console (Apps → Google Workspace → Gmail → Authenticate email), checks that
      **DKIM** is turned on for the domain. Google's SPF record is usually already in DNS; if not, add it.
   5. Test: in the app's *Console*, run `python manage.py sendtestemail your.name@osea.ca` and check it arrives
      (not in junk).

   Google allows about 2,000 emails a day from one account, far more than OSEA needs. If the app password
   is ever exposed, delete it in the same screen and create a new one; nothing else changes.
7. **First administrator.** In the app's *Console*, run `python manage.py createsuperuser` and
   enter an OSEA email and a strong password. Sign in, and set up two-step sign-in when asked.
   Add the other administrators from **Administrators** in the site; they receive an email to
   choose their own password.
8. **Real data.** Add school boards, schools and the school year. Do **not** load the demo data
   (`seed_demo` refuses to run on the live site anyway).

## Check after going live

- [ ] `https://` address works and plain `http://` redirects to it
- [ ] No yellow "Development/Test site" banner
- [ ] Sign-in asks administrators for their two-step code
- [ ] A test coach sign-up receives the confirmation email (check junk folders)
- [ ] `/healthz` shows `ok`
- [ ] Activity log shows the test actions with the right names
- [ ] Download everything (Exports) works, then delete the test file
- [ ] After a week with no HTTPS problems, set `DJANGO_HSTS_SECONDS=31536000` (browsers then always use HTTPS)

## Updating the live site

1. Changes are tested automatically on GitHub; only merge to `main` when the checks pass.
2. In DigitalOcean, click **Deploy** on the app. The database is updated first, then the new
   version replaces the old one with no downtime.
3. If something goes wrong, use **Rollback** in DigitalOcean to the previous version.
