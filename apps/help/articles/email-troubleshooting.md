---
title: Email problems
slug: email-troubleshooting
summary: The connection test, what the common failures mean, and the email activity log.
parent: email-and-password-reset
audience: everyone
order: 10
published: true
keywords: [test connection, email test, email log, failed email, accepted, delivered, bounce, timed out, rejected credentials, refused from address, dismiss banner, send test message]
pages: []
---
## Testing a connection

Each connection card has a **Test** button that checks that saved connection step
by step without sending anything. A **Send a test message** panel below the list
delivers a real message so you can confirm it arrives.

Either way, **save your edits first** — the test runs against the *saved*
connection. The report walks the same steps a real send does, so the first ✗
tells you which setting is wrong:

1. **Configuration** — are the required fields filled in at all
2. **Resolve hostname** — does the server address exist
3. **Connect** — is anything listening on that port
4. **Secure the connection** — does the encryption mode match the port
5. **Authenticate** — are the username and password accepted
6. **Send a test message** — *optional*, only if you fill in an address

That last step is worth doing. A connection can pass every earlier check and
still fail to deliver, because the server refuses to relay mail *from* your
chosen from-address. Only an actual send catches that.

## What the common results mean

| Result | Usually means |
|---|---|
| **Nothing is accepting connections on that port** | The port is wrong for the encryption mode. Use 587 with STARTTLS, or 465 with implicit TLS. |
| **Timed out** | A firewall is dropping the connection, or your internet provider blocks outbound mail ports. |
| **The server rejected the credentials** | A normal password where an [app password](/help/email-and-password-reset/) is required. The server's own explanation is shown too. |
| **The server refused the from address** | Set the from address to match the account you authenticate as. |

## The email log

Every message BitGigs tries to send — tests and real mail alike — is recorded in
the **Email log** (the button is on the Email tab): when, which **connection**
sent it, to whom, the subject, and the outcome; a failure also shows **why**. Only
this metadata is kept, never the contents. The log holds the most recent 200
attempts.

If a send **fails**, a red banner appears on your **dashboard** with a link
straight to the log. It stays until you press **Dismiss** — merely opening the log
doesn't clear it — so a failure that happened while you weren't looking can't slip
by unnoticed.

## "Accepted" is not "delivered"

**Accepted** means the mail server *took* the message for delivery. It is **not**
proof it landed in an inbox.

Mail works in relays: a server can accept a message and only later discover the
address doesn't exist, at which point a "delivery failed" notice bounces back to
your own inbox a few minutes later. There's no reliable way for BitGigs to know
that at send time, so *Accepted* is as far as the log can honestly go. If in
doubt, send yourself a test message and check it actually arrives.

> Invites that fail have their own recovery flow — see
> [When an invite doesn't send](/help/invite-problems/).
