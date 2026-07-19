---
title: Creating your account
slug: onboarding-account
summary: The owner account — email + password, or through your identity provider.
parent: first-time-setup
audience: public
order: 2
published: true
keywords: [account, owner, email, username, display name, password, rules, checklist, sso, oidc, identity provider, method]
pages: [core:onboarding-account-method, core:onboarding-account-email]
---
BitGigs is a **single-user** app: the one account created here is the owner
and administrator of everything.

If the server has single sign-on configured you'll first be asked **how** to
create it — with your identity provider, or with an email and password. (No
SSO configured? You go straight to email + password.) Whichever you pick, you
can add the other sign-in method later under **Settings → Sign-in**.

## Email + password

- Your **email is also your username** — it's what you'll type to sign in.
- The **display name** is just for greetings ("Good morning, …").
- The password checklist fills in live as you type. A password needs:
    - at least **8 characters**,
    - at least one **lowercase**, one **UPPERCASE**, one **number** and one
      **symbol**,
    - no runs like `abc` or `aaa`,
    - and it can't look like your email or be a commonly used password.

## Through your identity provider

The SSO button sends you to your provider and back. Before anything is
created, BitGigs shows the identity it received — name, email, ID — on a
**confirm page**, so the wrong provider account can't silently become the
owner. An account created this way has **no password** at first; you can set
one later under **Settings → Sign-in** if you want both ways in.
