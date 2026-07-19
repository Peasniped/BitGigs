---
title: Editing this manual
slug: editing-the-manual
summary: Write and organise help articles — Markdown editor, revisions, trash and page mapping.
parent:
audience: staff
order: 90
published: true
keywords: [help, manual, editor, markdown, article, revision, revert, trash, restore, keywords, slash, staff]
pages: []
---
This manual is editable from inside BitGigs. The **manage page** (reachable
from the full manual, staff only) lists every article with search, per-column
filters and sorting.

## Writing

Articles are **Markdown** — tables, fenced code, task lists (`- [ ]`),
`~~strikethrough~~` — with a live preview beside the editor. The toolbar
inserts common formatting, or type **`/`** in the text to pick from the same
commands inline. The slug auto-fills from the title until you touch it, and
the editor warns before you leave with unsaved changes.

## Reaching readers

Three things decide where an article surfaces:

- **Pages** — tick the app pages it belongs to; the **F1 / ?** popup shows it
  there first.
- **Keywords** — extra search terms (they rank just below the title).
- **Parent & order** — where it nests in the manual's table of contents, and
  its position among siblings.

You can deep-link into the app from an article — plain Markdown links to
paths like `/settings/?tab=display` work, and anchors can point at a specific
setting.

## Safety nets

- **Revisions** — every save keeps a snapshot (the last 20); open an
  article's history to revert to any of them.
- **Trash** — deleting an article archives it. It disappears from readers but
  sits in the Trash (button beside *New article*) until you restore it or
  delete it permanently. Only *Delete permanently* / *Empty trash* is final —
  it also discards the article's revisions.
