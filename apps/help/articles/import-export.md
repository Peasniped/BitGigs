---
title: Import & export
slug: import-export
summary: Move your data in and out of BitGigs.
parent:
audience: everyone
order: 80
published: true
keywords: [import, export, backup, data, csv, migrate]
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
