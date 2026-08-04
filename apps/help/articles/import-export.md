---
title: Import & export
slug: import-export
summary: Move your data in and out of BitGigs.
parent:
audience: everyone
order: 80
published: true
keywords: [import, export, backup, data, migrate, restore, json, conflicts, map workplace, blank workplace, skip]
pages: [data_io:main]
---
Export produces a file of your data you can keep as a backup or move to another
install. Import brings one back in.

**Keep a fresh export before a big import**, just in case.

## Importing is all-or-nothing

Rows are checked before anything is written. Invalid **shifts** are skipped and
counted; invalid **term sets** abort the whole import, so bad pay terms never land
half-applied.

## Workplaces the file doesn't fully describe

An export can mention a workplace on a shift without describing the workplace
itself. For each unmatched name the review page says which case it is, and offers:

| Choice | What you get |
|---|---|
| **Create with its imported settings** | The workplace exactly as the file has it, contracts and pay terms included. Only offered when the file actually describes it. |
| **Create blank workplace** | The shifts, but none of the file's settings — you enter its pay terms yourself afterwards. |
| **Map to an existing workplace** | Files its shifts under one you already have. |
| **Skip** | Don't import that workplace's shifts at all. |

## Importing during first-time setup

A fresh install can be filled straight from an export — pick **import** on the
[Start step](/help/onboarding-start/). It's the same machinery as this page, with
two differences: it can be run **more than once** (later files see the workplaces
earlier ones created, so a renamed workplace can be mapped onto an existing one),
and it hands off to [Review](/help/onboarding-review/), which says whether the
file covered everything setup needs.
