# Putting the OSEA platform online

**Status: not deployed.** Nothing in this guide has been done yet. OSEA must approve
hosting and create the accounts below before anything goes online.

This guide assumes DigitalOcean's Toronto region (data stays in Canada). The
platform is a standard Django app, so another Canadian host would work with
small changes.

## What OSEA needs to set up (once)

| Account | Why | Approximate cost |
|---|---|---|
| DigitalOcean (in OSEA's name, OSEA's billing) | Runs the website and the database | US$5–12/month app + ~US$15/month database |
| Email service (Postmark, or Amazon SES Canada) | Sends sign-in, approval and match emails | US$0–15/month |
| Access to OSEA's domain settings (DNS) | Points e.g. `app.osea.ca` at the platform and lets the email service send as OSEA | usually already paid for |

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
   | `DJANGO_ALLOWED_HOSTS` | the site address, e.g. `app.osea.ca` |
   | `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://` + the site address |
   | `OSEA_CLIENT_IP_HEADER` | `HTTP_DO_CONNECTING_IP` (lets sign-in limits see real visitor addresses) |
   | `DJANGO_EMAIL_BACKEND` | `django.core.mail.backends.smtp.EmailBackend` |
   | `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | from the email service (*Encrypted* for user and password) |
   | `DEFAULT_FROM_EMAIL` | e.g. `OSEA <no-reply@osea.ca>` |

   Do **not** set `OSEA_ENVIRONMENT_LABEL` or `OSEA_REQUIRE_ADMIN_2FA` on the live site.
   (A separate *test* copy should set `OSEA_ENVIRONMENT_LABEL=Test` so nobody mistakes it for the real one.)
4. **Before each release** the app runs `python manage.py migrate` and `createcachetable`
   automatically (the "prepare-database" job), which updates the database structure.
5. **Domain.** In OSEA's DNS settings, add the record DigitalOcean shows (a CNAME for e.g. `app`).
   DigitalOcean then provides the HTTPS certificate automatically.
6. **Email.** In the email service, verify the sending domain by adding the DNS records it shows
   (SPF/DKIM). Until this is done, emails may land in junk folders or not arrive at all.
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
