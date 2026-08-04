---
title: API access & keys
slug: api-access
summary: Read your BitGigs data from scripts with an API key created in Settings → API.
parent: settings-and-sign-in
audience: everyone
order: 40
published: true
keywords: [api, key, token, bearer, script, python, income, endpoint, scope, revoke, expire, automation]
pages: [core:settings]
---
BitGigs has a small read-only HTTP API so your own scripts can pull your data —
for example monthly gross/net income. It runs against your own server; nothing is
sent anywhere else.

## API keys

Every request needs an **API key**, created under **Settings → API**. A key has a
**name**, an optional **expiration date**, and **granular access**: all endpoints,
or only the ones you tick.

The full key is shown **exactly once**, right after you create it — BitGigs stores
only a fingerprint, so it cannot be shown again. Copy it somewhere safe; if you
lose it, revoke the key and create a new one.

**Revoking** stops a key working immediately. Revoked or expired keys stay in the
list until you delete them.

## Making a request

Send the key in the `Authorization` header:

```
Authorization: Bearer bg_…your key…
```

The Settings → API tab shows a ready-to-run Python example for every endpoint,
with your server's address already filled in. There is also a command-line
client in the repository:

```
python scripts/api_client.py --key bg_… ping
python scripts/api_client.py --key bg_… income --year 2026
python scripts/api_client.py --key bg_… income --start 2026-01 --end 2026-06
```

## Endpoints

| Endpoint | What it returns |
|---|---|
| `GET /api/v1/income/` | Gross and net income per month, per workplace and combined — the same numbers as the Analytics page. Use `year=`, `year=&month=`, or `start=`/`end=` (YYYY-MM). |
| `GET /api/v1/ping/` | Confirms a key works and shows its name, access and expiry. |

Amounts are returned as strings in DKK with a dot decimal separator
(`"12345.67"`), so they can be parsed exactly.

## If a request fails

The API answers with a JSON error naming the problem: a missing or unknown key,
a revoked or expired key, or a key that doesn't have access to that endpoint.
Check the key's row on the Settings → API tab — its status badge shows whether
it is still active.
