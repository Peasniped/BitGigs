---
title: Email & password reset
slug: email-and-password-reset
summary: Connect a mail server so BitGigs can email you a password reset link and send calendar invites.
parent: settings-and-sign-in
audience: everyone
order: 20
published: true
keywords: [email, smtp, mail, gmail, outlook, fastmail, app password, starttls, port 587, port 465, mail connection, no-reply, roles, used for, multiple mail servers, password reset, forgot password]
pages: [core:settings]
---
BitGigs can send mail through a mail server **you** choose. It's entirely
optional — everything else works without it — and **off until you turn it on**.
It powers the "forgot your password" link and, if you use them,
[calendar invites](/help/calendar-invites/).

Set it up under **[Settings → Email](/settings/?tab=email)**.

## What gets sent where

Only what you ask for: a password reset link to your own sign-in address, and
calendar invites to the addresses you name on a contract. Nothing about your
shifts, pay or workplaces goes anywhere else.

Bear in mind the mail server you point this at *is* a third party unless you run
it yourself — with Gmail, your reset emails pass through Google. That's your call
about your own mail account, which is exactly why this is opt-in and why BitGigs
never picks a provider for you.

## Connections and what they're used for

A **mail connection** is one SMTP setup — a server, a sign-in, a from-address.
You can keep more than one and choose which sends which kind of mail:

- **System mail** — the transactional stuff, i.e. password reset links.
- **Calendar invites** — the invites your shifts turn into.

A common reason to keep two: send system mail from a **no-reply** mailbox and
invites from **your own address** so replies reach you. Pick a connection for
each in the **Used for** panel, or leave both on **Default**. One server? Add one
connection and leave both on Default.

The **master switch** turns all outgoing mail on or off. **Clear all** wipes every
connection back to a fresh, disabled state.

## Adding a connection

Press **Add connection** (or **Edit** on a card). **Quick setup** fills in server,
port and encryption for a common provider; then add your own credentials. Give it
a **name** so you can tell setups apart. The first connection becomes the
**default**; **Make default** on any card moves that.

| Provider | Server | Port | Encryption |
|---|---|---|---|
| Gmail / Google Workspace | `smtp.gmail.com` | 587 | STARTTLS |
| Outlook / Microsoft 365 | `smtp.office365.com` | 587 | STARTTLS |
| Fastmail | `smtp.fastmail.com` | 465 | Implicit TLS |

Anything else: ask your provider for their **SMTP** (outgoing) settings.

> **Your normal account password usually won't work.** Gmail, Outlook and
> Fastmail all require an **app password** — a separate password generated for one
> application. For Gmail, turn on 2-step verification first, then create an App
> Password in your Google account's security settings.

**From address** is what recipients see. Most providers only let you send from the
account you signed in as, so if in doubt make it the same as the username.

Your password is stored **encrypted**, keyed off the server's
`DJANGO_SECRET_KEY` — a stolen copy of the database alone doesn't reveal it. The
flip side: change that key and the stored password can no longer be read, so
BitGigs will ask you to enter it again.

## Resetting a forgotten password

Once mail works, the login page's **Forgot your password?** offers to email you a
reset link. The link lasts **two hours** and works **once**; requesting a new one
cancels any older link. Turn it off with **Offer 'Forgot your password?'** if you'd
rather keep recovery console-only.

If mail isn't configured — or the mail server is the thing that broke — recovery
is always available from the server console:

```
python manage.py changepassword your@email.address
```

Run it in the BitGigs project directory with the virtualenv active (in
development, add `--settings=bitgigs.settings.local`).

If you sign in with single sign-on and have no password set, there's nothing to
reset — recover through your identity provider instead. See
[Sign-in & single sign-on](/help/sign-in-and-sso/).

> Not arriving? [Email problems](/help/email-troubleshooting/) covers the
> connection test, the common failures and the activity log.
