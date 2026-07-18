---
title: How income projection works
slug: analytics-projection
summary: What Actual, Planned and Projected mean on the analytics chart.
audience: everyone
order: 30
published: true
keywords: [analytics, projection, planned, projected, forecast, income]
pages: [analytics:overview]
---
The analytics projection fills in each month with the best information it has,
and labels which kind it used.

## The three states

| State | When it's used |
|---|---|
| **Actual** | Past months — your approved shift hours. |
| **Planned** | Current/future months where you have planned shifts. |
| **Projected** | Fallback — a trailing average of recent active months. |

The current month is a **hybrid**: already-approved hours plus hours still
planned after today.

## Notes

- The trailing average only counts months a contract was **active**, so the
  first months of a new job aren't dragged down by pre-hire zeros.
- The Actual / Planned / Projected legend entries are clickable — use them to
  show or hide each category on the chart.
