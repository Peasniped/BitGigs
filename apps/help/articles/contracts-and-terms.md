---
title: Contracts & pay terms
slug: contracts-and-terms
summary: How contracts and date-versioned term sets define what you're paid.
parent: workplaces
audience: everyone
order: 10
published: true
keywords: [contract, term set, salary, hourly, rate, effective, dates]
pages: [workplaces:workplace-detail]
---
Pay terms are **date-versioned**, so your history stays correct when a rate
changes. Two pieces work together:

- A **contract** is just a named container. It has **no dates**.
- A **term set** carries the actual terms (salaried vs. hourly, the amounts,
  weekly hours) and a date range: an `effective from` and an optional
  `effective until`.

## How dates are read

A term set "runs until the next one starts". To find the terms for a given day,
BitGigs picks the **latest term set whose *effective from* is on or before that
day**. Only an `effective until` on the last term set actually **closes** the
contract.

## Rules to know

- [ ] Term sets for one workplace **must not overlap** — you'll get an error on
      save if they do.
- [ ] To change your pay, **add a new term set** with the new `effective from`;
      never edit an old one (that would rewrite history).

## Example

| Term set | Effective from | Rate |
|---|---|---|
| First | 2025-01-01 | 145 kr/h |
| Raise | 2025-09-01 | 160 kr/h |

A shift on 2025-08-30 uses 145; a shift on 2025-09-02 uses 160.
