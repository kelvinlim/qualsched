# Privacy Policy

Last updated: 28 August 2026

QualSched Web (“QualSched”) is a researcher tool for scheduling Qualtrics ecological
momentary assessment (EMA) invitations. It is operated by Kelvin O. Lim at the
University of Minnesota.

This page describes how QualSched handles information. It is an operational disclosure
that matches how the software works, not a review by University counsel. University
privacy information is also at [privacy.umn.edu](https://privacy.umn.edu/).

Questions: [kolim@umn.edu](mailto:kolim@umn.edu).

## Who this app is for

QualSched is for authorized researchers, not study participants. Participants do not
sign in here. Their contact records stay in Qualtrics.

## Information we receive from Google

Researchers sign in with Google. QualSched requests only the `openid`, `email`, and
`profile` scopes. From the Google ID token we read:

- email address
- Google account identifier (`sub`)
- display name

We do not request Google Health, Fitbit, Drive, Calendar, or other sensitive scopes.
We do not store Google access tokens or refresh tokens. The grant is used only to prove
identity against the QualSched allowlist, then discarded.

## What we store

In the QualSched database we keep:

- Researcher account: email, Google `sub`, display name, whether the account is a
  superuser, and when it was created
- Qualtrics connection settings the researcher saves (data center, directory and
  library ids, survey profile settings)
- The researcher’s Qualtrics API token, **encrypted at rest** (Fernet). The browser
  never receives that token.

We do **not** store:

- Participant names, phone numbers, emails, time slots, time zones, or other contact
  PHI. Those live in Qualtrics. QualSched proxies them for the signed-in researcher and
  discards the payload after the response.
- Google access or refresh tokens

## Cookies

- `qs_session` — HttpOnly session cookie (Fernet-encrypted user id). Lifetime is 12
  hours. `Secure` on HTTPS; `SameSite=Lax`.
- `qs_oauth_state` — short-lived HttpOnly cookie used during the Google sign-in
  round-trip (about 10 minutes), then deleted.

No advertising or third-party analytics cookies.

## Who can sign in

Google proving identity is not enough. QualSched then checks, in order:

1. An existing researcher row in this app
2. An email listed as a bootstrap superadmin
3. An email whose domain is on the configured allowlist (on the hosted instance,
   typically `@umn.edu` and subdomains such as `@med.umn.edu`)

Gmail is not campus-wide. Accounts that match none of those lists cannot sign in.

## How Qualtrics data is used

When a signed-in researcher uses QualSched, the server calls Qualtrics with that
researcher’s API token to list and update mailing-list contacts and to book or cancel
survey invitations. Qualtrics remains the system of record for participant data.
QualSched does not sell researcher or participant information.

## Retention

Researcher accounts and Qualtrics connection settings remain until an operator removes
them. Session cookies expire after 12 hours or when the researcher signs out. Google
tokens are never retained.

## Changes

If this policy changes, we will update this page and the “Last updated” date.

## Contact

Kelvin O. Lim, University of Minnesota — [kolim@umn.edu](mailto:kolim@umn.edu).
See also the [Terms of Service](../terms).
