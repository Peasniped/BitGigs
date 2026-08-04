---
title: Settings & sign-in
slug: settings-and-sign-in
summary: Display preferences, switching features on and off, and where the rest of the settings live.
parent:
audience: everyone
order: 70
published: true
keywords: [settings, preferences, theme, dark mode, light mode, auto, accent, colour, color, mask money, features, turn off, hide, disable, payroll, vacation, commuting, analytics, tabs]
pages: [core:settings]
---
Everything configurable lives under **More › Settings**, split across tabs.
Changes **save as you make them** — there's no Save button to remember.

## Display

- **Theme** — Light, Dark, or **Auto** (follows your operating system, switching
  live when it does). There's also a one-tap toggle in the **More** menu; while
  Auto is active that menu item links back to this setting instead.
- **[Accent colour](/settings/?tab=display#div_id_accent_color_picker)** — one
  colour drives buttons, links, tints, gradients and focus rings. Pick a swatch,
  use the colour wheel, or type a hex value. (Charts keep their fixed
  actual/planned/projected colours so their meaning never changes.) A workplace
  with [its own accent](/help/workplace-editing/) overrides this on its own pages.
- **Colour shifts by type** — tint calendar chips by
  [shift type](/help/shift-types/).
- **Mask money** — replace every amount with dots, for demos and screenshots.
  Hours, dates and percentages stay readable.

## Features

BitGigs covers more ground than most people need. The **Features** tab switches
off the parts you don't use — **Payroll periods**, **Vacation & feriepenge**,
**Commuting** and **Analytics** — each with a switch and a description of what
goes away.

Switching one off does two things: its menu entry disappears, and its pages stop
opening. That second part matters — a bookmark or an old link would otherwise
still walk you into a page you'd turned off. Follow one anyway and BitGigs takes
you to the dashboard and says which feature is off.

**Nothing is deleted.** A switch only changes what you can *reach*; your shifts,
payslip lines and commuting days stay exactly where they are. There's no risk in
trying it.

A feature with settings of its own keeps them on its card, so its on/off switch
and its behaviour sit together — Analytics carries **projection method**,
**trailing months** and **use planned shifts** there. Those fold away when the
feature is off, but they're remembered.

## The other tabs

| Tab | What's there |
|---|---|
| **[Email](/help/email-and-password-reset/)** | Mail connections, so BitGigs can send you a password reset link. |
| **[Calendar](/help/calendar-integration/)** | Read a personal calendar in; send shifts out as invites. |
| **[API](/help/api-access/)** | Keys for reading your data from your own scripts. |
| **Jobs** | The background scheduler and its task queue. |
| **[Sign-in](/help/sign-in-and-sso/)** | Your password, and an optional identity provider. |
| **About** | Version, build and deployment facts about this install. |

> Email and Calendar are the only two settings that reach outside your server,
> and both go somewhere you named — see
> [Your data stays with you](/help/your-data/).
