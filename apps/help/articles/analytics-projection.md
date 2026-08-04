---
title: How income projection works
slug: analytics-projection
summary: What Actual, Planned and Projected mean on the analytics chart, and why rows are payroll periods.
audience: everyone
order: 30
published: true
keywords: [analytics, projection, planned, projected, forecast, income, trailing average, mixed, part planned, avg h/mo]
pages: [analytics:overview]
---
The projection fills each row with the best information it has, and labels which
kind it used.

Each row is **one payday**, so it covers that workplace's
[payroll period](/help/payroll/) rather than the calendar month — the period's own
dates are printed next to the month name.

## The three states

| State | When it's used |
|---|---|
| **Actual** | Approved shift hours — work that is done and logged. |
| **Planned** | Shifts you've planned but not yet approved, and salaried pay for days still ahead. |
| **Projected** | Fallback for a period holding nothing yet — a trailing average of recent periods. |

Most periods are a **mix**. The current one usually holds approved hours *and*
hours still planned, so the row shows both (`12,0 h` as `5,0 + 7,0`), the chart
stacks them, and the row is tagged **part planned**.

A period only falls back to the projection when it has **nothing real in it** —
no approved and no planned hours. A period that already holds some hours is
trusted as it stands rather than having an average added on top, which would
count the same work twice.

## Salaried work

A salary is known from your contract, so it's never *projected*. It accrues per
calendar day: days up to and including today are **actual**, later ones
**planned**. So a period that has fully passed is all actual, a future one all
planned, and the current one splits at today.

## How the projection is worked out

Each projected period looks back over the previous few periods — how many is
**Settings → Features → Analytics** — and averages the hours you worked. The
figure therefore **changes month to month** rather than repeating one number
through to December.

The look-back rolls forward: past your last real data it uses what the previous
period came to, so a strong September lifts the months after it. Anything you
*plan* counts too, which is why adding shifts to a future month nudges the
projections beyond it.

Two kinds of period are skipped rather than counted as zero — months before the
job started, and months you were **salaried** at that workplace (those hours were
never paid by the hour).

It averages **hours**, then prices them at each period's own rate, so a pay rise
flows straight into the forecast instead of being watered down by what you earned
before it.

## Notes

- A shift planned for **today** counts as planned — it hasn't been worked yet.
- A closed period is whatever you actually worked, **including zero**. An empty
  past month is a fact, not a gap to guess at.
- Each shift is priced at the rate in force on **its own date**, so a mid-period
  raise pays the old rate before it and the new rate after.
- **Avg h/mo** on a workplace card looks back at what you actually worked. It's a
  summary, not the forecast, so it can differ from the projected months below it.
- A period the contract only partly covers gets a **partial** projection — a job
  ending on the 15th projects about half a period.
- The Actual / Planned / Projected legend entries are **clickable** — use them to
  show or hide each band. Hiding one subtracts just that band, so a mixed period
  keeps the part you're still looking at.

> The other analytics page, [Rate history](/help/rate-history/), charts how your
> pay rate itself has moved over time.
