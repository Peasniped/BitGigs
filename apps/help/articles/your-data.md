---
title: Your data stays with you
slug: your-data
summary: Everything runs on your own server — what leaves it, and how to back it up.
parent:
audience: everyone
order: 85
published: true
keywords: [privacy, data, server, self-hosted, backup, external, third party, security, encrypted, telemetry, cloud]
pages: [data_io:main]
---
BitGigs is self-hosted and built on one rule: **your data never leaves your
server**. Shifts, pay, tax numbers, workplaces — none of it is sent to any
external or third-party service. No analytics, no telemetry, no cloud AI.

## The only outbound connections

Both are optional, off by default, and go to a server **you** name:

1. **[Single sign-on](/help/sign-in-and-sso/)** — your own identity provider.
2. **[Mail](/help/email-and-password-reset/)** — the mail server you configure,
   used only for what you asked it to do: a password reset link to your own
   address, and [calendar invites](/help/calendar-invites/) to addresses you
   named.

A calendar you [read in](/help/calendar-overlay/) is fetched *from* a URL you
paste — nothing of yours is sent out along the way.

## How secrets are stored

- Your password is stored as a hash, never readable.
- The mail server password and calendar URLs are **encrypted at rest**.
- [API keys](/help/api-access/) are stored only as fingerprints — the real key is
  shown once at creation and can never be recovered from the server.

## Backing up

Your data lives in the app's database on your server. For a portable copy use
[Export](/help/import-export/) — and take one before any big import or upgrade.
Uploaded workplace icons live in the server's `media/` folder.
