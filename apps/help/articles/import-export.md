---
title: Import & export
slug: import-export
summary: Move your data in and out of BitGigs.
parent:
audience: everyone
order: 80
published: true
keywords: [import, export, backup, data, csv, migrate, onboarding, restore]
pages: [data_io:main]
---
Import and export let you back up your data or bring existing records in.

## Exporting

Export produces a file of your data you can keep as a backup or move to another
install.

## Importing

Importing is **all-or-nothing** and validated:

- Rows are checked before anything is written.
- Invalid **shifts** are skipped and counted; invalid **term sets** abort the
  whole import (so bad pay terms never land half-applied).

Keep a fresh export before a big import, just in case.

## Importing during first-time setup

A fresh install can be filled straight from an export — pick **import** on the
[Start step](/help/onboarding-start/) instead of typing everything in. It's the
same machinery as this page, with two differences: it can be run **more than
once** (later files see the workplaces earlier ones created, so a renamed
workplace can be mapped onto an existing one), and it hands off to
[Review](/help/onboarding-review/), which says whether the file covered
everything setup needs.

## Workplaces the file doesn't fully describe

An export can mention a workplace on a shift without describing the workplace
itself — for example if the shifts were exported but the workplaces weren't. For
each unmatched name the review page says which case it is, and offers:

- **Create with its imported settings** — restores the workplace exactly as the
  file has it, including its contracts and pay terms. Only offered when the file
  actually describes it.
- **Create blank workplace** — takes the shifts but none of the file's settings.
  You'll enter its pay terms yourself afterwards.
- **Map to an existing workplace** — file its shifts under one you already have.
- **Skip** — don't import that workplace's shifts at all.
