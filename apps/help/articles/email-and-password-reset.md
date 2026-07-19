---
title: Email & password reset
slug: email-and-password-reset
summary: Connect a mail server so BitGigs can send you a password reset link.
parent: settings-and-sign-in
audience: everyone
order: 75
published: true
keywords: [email, smtp, mail, gmail, outlook, password reset, forgot password, app password, starttls, port 587, port 465, test connection]
pages: [core:settings]
---
BitGigs can send mail through a mail server **you** choose. It is entirely
optional — everything else in the app works without it — and it is **off until
you turn it on**. Today it powers the "forgot your password" link; calendar
invites will use the same connection later.

Set it up under **[Settings → Email](/settings/?tab=email)**.

## What gets sent where

Only what you ask BitGigs to send: a password reset link, addressed to your own
sign-in address. Nothing about your shifts, pay or workplaces goes anywhere.

Bear in mind that the mail server you point this at *is* a third party unless you
run it yourself — if you use Gmail, your reset emails pass through Google. That's
your call to make about your own mail account, which is exactly why this is
opt-in and why BitGigs never picks a provider for you.

## Connecting a server

Use **Quick setup** to fill in the server address, port and encryption for a
common provider, then add your own credentials:

| Provider | Server | Port | Encryption |
|---|---|---|---|
| Gmail / Google Workspace | `smtp.gmail.com` | 587 | STARTTLS |
| Outlook / Microsoft 365 | `smtp.office365.com` | 587 | STARTTLS |
| Fastmail | `smtp.fastmail.com` | 465 | Implicit TLS |

Anything else: ask your provider for their **SMTP** (outgoing) settings.

> **Your normal account password will usually not work.** Gmail, Outlook and
> Fastmail all require an **app password** — a separate password generated for
> one application. For Gmail you must turn on 2-step verification first, then
> create an App Password in your Google account's security settings.

**From address** is what recipients see. Most providers only let you send from
the account you signed in as, so if in doubt make it the same as the username.

Your password is stored **encrypted**, using a key derived from the server's
`DJANGO_SECRET_KEY`. A stolen copy of the database alone doesn't reveal it. The
flip side: if that key is ever changed, the stored password can no longer be
read and BitGigs will ask you to enter it again.

## Testing it

Save your settings, then press **Run test**. The test walks through the same
steps a real send does and reports each one, so the first ✗ tells you which
setting is wrong:

1. **Configuration** — are the required fields filled in at all
2. **Resolve hostname** — does the server address exist
3. **Connect** — is anything listening on that port
4. **Secure the connection** — does the encryption mode match the port
5. **Authenticate** — are the username and password accepted
6. **Send a test message** — *optional*, only if you fill in an address

That last step is worth doing. A connection can pass every earlier check and
still fail to deliver, because the server refuses to relay mail *from* your
chosen from-address. Only an actual send catches that.

Common results:

- **"Nothing is accepting connections on that port"** — the port is wrong for the
  encryption mode. Use 587 with STARTTLS, or 465 with implicit TLS.
- **"Timed out"** — a firewall is dropping the connection, or your internet
  provider blocks outbound mail ports.
- **"The server rejected the credentials"** — usually a normal password where an
  app password is required. The server's own explanation is shown too.
- **"The server refused the from address"** — set the from address to match the
  account you authenticate as.

## Resetting a forgotten password

Once mail works, the login page's **Forgot your password?** offers to email you a
reset link. The link lasts **two hours** and works **once** — requesting a new one
cancels any older link. You can turn this off with **Offer 'Forgot your
password?'** on the Email tab if you would rather keep recovery console-only.

If mail is not configured, or the mail server is the thing that broke, recovery
is always available from the server console:

```
python manage.py changepassword your@email.address
```

Run it in the BitGigs project directory with the virtualenv active (in
development, add `--settings=bitgigs.settings.local`).

If you sign in with single sign-on and have no password set, there is nothing to
reset — recover through your identity provider instead. See
[Settings & sign-in](/help/settings-and-sign-in/).
