# QualSched User Guide

QualSched books Qualtrics survey invitations ahead of time. You tell it when each
participant should be prompted, it works out every individual invitation, shows you the
full list, and sends it to Qualtrics. Qualtrics then holds each invitation until its
moment arrives — nothing has to stay running on your computer, and you do not have to be
awake at 6am.

It was built for EMA studies, where each person is prompted several times a day for
several weeks. That means a lot of invitations: a participant prompted four times a day
for twenty days needs eighty separate invitations, each at a specific minute in their own
time zone.

This guide is for the person running the study. You will not need the command line, and
you do not need to understand how Qualtrics works underneath.

## Contents

- [Before you start](#before-you-start)
  - [Words used in this guide](#words-used-in-this-guide)
  - [What you need in Qualtrics first](#what-you-need-in-qualtrics-first)
  - [Getting your API token](#getting-your-api-token)
  - [What the window looks like](#what-the-window-looks-like)
- [Which setup do I need?](#which-setup-do-i-need)
- [Path A — Import your existing setup](#path-a--import-your-existing-setup)
- [Path B — Set up from scratch](#path-b--set-up-from-scratch)
- [You're set up](#youre-set-up)
  - [Three things to check before your first send](#three-things-to-check-before-your-first-send)
  - [Do a rehearsal first](#do-a-rehearsal-first)
- [Everyday use: sending invitations](#everyday-use-sending-invitations)
- [Common tasks](#common-tasks)
- [Reference: the scheduling fields](#reference-the-scheduling-fields)
- [Troubleshooting](#troubleshooting)

---

# Before you start

QualSched sends invitations to things that already exist in Qualtrics. It does not build
your survey, it does not create your participant list, and it does not write your
invitation text. All of that happens in Qualtrics first; QualSched only decides *when*
each person gets prompted and books it.

## Words used in this guide

Qualtrics uses several words for things you will meet on the setup screens. You do not
need to know these in depth, but you do need to recognise them.

**Data center** — Qualtrics runs several separate installations around the world, and
your institution lives on exactly one. Its short name appears at the front of your
Qualtrics web address: if you log in at `umn.yul1.qualtrics.com`, your data center is
`yul1`. Common ones are `yul1`, `ca1`, `iad1`, and `gov1`. Everything QualSched does has
to be aimed at the right one.

**API token** — a long password that lets QualSched act on your behalf without you
logging in each time. It is tied to your personal Qualtrics account.

**XM Directory** — Qualtrics' address book. Your institution has one big pool of people,
sometimes shown as "Directory" and sometimes as "contact pool". It is usually called
something like `POOL_…`.

**Mailing list** — one named group of people inside that directory, for example everyone
in your study. QualSched works on exactly one mailing list at a time. Its name starts
with `CG_`.

**Library and message template** — your saved invitation wording. A library holds
templates; `GR_…` is a shared group library and `UR_…` is your personal one. You need one
template for SMS and, if you send email, a **separate** one for email. An SMS template
will not render correctly as an email.

**Embedded data** — extra fields Qualtrics stores against each person, alongside their
name and phone number. QualSched keeps each participant's schedule here: when they start,
how many days they run for, and at what times. Because it lives in Qualtrics rather than
on your computer, any colleague with access sees the same values.

**Distribution** — Qualtrics' word for one invitation to one person at one moment. A
twenty-day, four-times-a-day participant produces eighty distributions.

## What you need in Qualtrics first

Five things need to exist before QualSched is any use. If you did not set up this study
yourself, ask your PI or Qualtrics administrator.

1. **A Qualtrics account with API access.** Some institutions switch API access off. If
   the API section described below is missing from your account settings, only your brand
   administrator can enable it — nothing in QualSched can work around that.
2. **Your survey**, built and active.
3. **A mailing list containing your participants.** Each person needs a **phone number**
   if you are sending SMS, or an **email address** if you are sending email. Phone numbers
   must include the country code, so `16125551234` rather than `6125551234`.
4. **Message templates in a library** — one for SMS, and a separate one for email if you
   will send email.
5. **An API token and your data center name.** Both come from the same settings page.

Where to find each one:

| Thing | Where in Qualtrics | Looks like |
| --- | --- | --- |
| Data center | Account Settings → Qualtrics IDs, or the front of your web address | `yul1`, `ca1`, `iad1`, `gov1` |
| API token | Account Settings → Qualtrics IDs → API | a long string of letters and numbers |
| Library ID | Account Settings → Qualtrics IDs → Libraries | `GR_…` or `UR_…` |
| Directory, survey, mailing list, templates | QualSched loads these for you | `POOL_…`, `SV_…`, `CG_…`, `MS_…` |

**You only have to type three things by hand:** the data center, the API token, and the
library ID. Everything else fills itself from dropdown lists once those are saved — but in
that order, because the mailing-list list cannot load until the directory is saved, and
the template lists cannot load until the library ID is saved.

One more thing worth knowing early: sending SMS requires an SMS-enabled Qualtrics licence
with credits available. If your licence does not include it, setup will appear to go
perfectly and invitations will fail at the moment you send them.

## Getting your API token

In Qualtrics, click your account icon → **Account Settings** → **Qualtrics IDs**. The API
box on that page either shows a token or offers to generate one.

Three warnings, all of which matter:

- **Generating a new token cancels the old one.** If a colleague's script, or another copy
  of QualSched, uses the same Qualtrics account, it will stop working the moment you press
  Generate. Ask before you do it.
- **Treat the token like your password.** Anyone holding it can read and change everything
  your Qualtrics login can. Do not email it and do not put it in a shared document.
- **QualSched stores it in your computer's own credential store** — Windows Credential
  Manager, macOS Keychain, or the Linux keyring — never in a settings file you could
  accidentally share.

You enter it once per account, on the Accounts screen.

## What the window looks like

![The QualSched window on first launch, with an empty sidebar](images/01-first-launch.png)
*The six screens down the left. Three of them are greyed out until you have set up an account and a survey profile.*

Down the left are six screens, in the order you use them:

| Screen | What it is for |
| --- | --- |
| **Accounts** | One per Qualtrics login: token, data center, directory, library |
| **Survey profile** | One per study: survey, mailing list, templates, default schedule |
| **Contacts** | Your participants and each one's schedule |
| **Schedule** | Work out the invitations, review them, send |
| **Distributions** | Invitations already booked, and cancelling them |
| **Import old config** | Read a settings file from the old command-line tool |

**Contacts, Schedule and Distributions stay greyed out** until you have both an account
and a survey profile selected. That is the whole purpose of setup.

At the bottom left, QualSched always shows which account, data center and profile you are
working in. Check it before doing anything irreversible — it is the only thing standing
between you and scheduling the wrong study.

---

# Which setup do I need?

There are two ways to get set up, and you only do one of them. Answer this question:

> **Do you have a file named `config_qualtrics….yaml`?**

That is the settings file the old command-line tool used. It is a small text file with a
name like `config_qualtrics_va.yaml` or `config_qualtrics.yaml`. Whoever sent this study's
invitations before QualSched existed will have one — it is worth asking, because importing
it saves you from copying a dozen ID codes by hand.

| Your answer | Where to go | How long |
| --- | --- | --- |
| **Yes** — I have it, or a colleague can send it | [Path A — Import your existing setup](#path-a--import-your-existing-setup) | About 10 minutes |
| **No** — new study, or nobody can find the file | [Path B — Set up from scratch](#path-b--set-up-from-scratch) | About 20 minutes, with Qualtrics open in a browser |

Skip whichever path you did not choose. Both finish in the same place,
[You're set up](#youre-set-up), and everything after that is the same for everybody.

> **Already set up and just here to send this week's invitations?** Go straight to
> [Everyday use](#everyday-use-sending-invitations).

---

# Path A — Import your existing setup

> **This is Path A.** Follow it only if you have a `config_qualtrics….yaml` file. If you
> do not, use [Path B](#path-b--set-up-from-scratch) instead.

## A1. Open the import screen

Click **Import old config** in the sidebar. Nothing you do on this screen changes anything
until you press Import at the end, so it is safe to look around.

You will want two files, though only the first is required:

- The **config file**, `config_qualtrics….yaml`.
- The **token file**, usually named `qualtrics_token` or similar, with no file extension.
  This holds the API token the old tool used.

## A2. Choose the files

![The import screen with both file paths filled in](images/02-import-choose-files.png)
*Step one: point QualSched at the old settings file, and at the token file if you have it.*

Press **Browse…** next to *Config file* and pick your `.yaml` file. If you have the token
file, press the second **Browse…** and pick that too — QualSched reads only the line
holding the API token and ignores everything else in it.

If you do not have the token file, leave it blank. You can paste the token in a moment, or
add it later.

Press **Read config**. Still nothing has been saved.

## A3. Check what was found

![The import review step, showing the settings found and several warnings](images/03-import-review.png)
*Everything QualSched pulled out of the file, plus anything it wants to warn you about.*

The four boxes at the top are the only things you can change here:

- **Account name** — QualSched guesses from the filename, so `config_qualtrics_va.yaml`
  becomes `VA`. Rename it to whatever you will recognise.
- **Data center** — check this is right.
- **Profile name** — this always arrives as "Imported project". Change it to your study's
  name now; it is the label you will pick from later.
- **Time zone** — the default for participants who do not specify their own.

Below that is a read-only table of everything else found: the directory, library, survey,
mailing list, message templates, time slots, contact method, link expiry, whether TLS
checking is on, and whether a token was found.

If the last row says the token was **not** found, an **API token** box appears underneath.
Paste your token there. You can also skip it and add it on the Accounts screen later — but
the account will not connect to anything until you do.

## A4. Warnings you will probably see

Old config files nearly always produce a few warnings. They do not stop the import, and
most explain themselves. Three are worth understanding:

> ⚠️ **"…is set more than once in this file. Used the last value…"**
>
> Read this one carefully. Real config files accumulate old settings alongside their
> replacements, and QualSched does what the old tool did: it keeps the last one. If the
> repeated setting is the **mailing list**, that decides which group of people gets
> invited — and you would find out it was wrong only after invitations had gone out. Open
> the file in a text editor and check.

**"No MESSAGE_ID_EMAIL in the file."** The old tool only ever sent SMS, so no config file
has an email template. If you plan to send email, pick one on the Survey profile screen
after importing. Ignore this if your study is SMS-only.

**"Email sender details … were hardcoded in the CLI."** This one always appears. The old
tool had a fixed from-address baked into it, so QualSched cannot recover yours and falls
back to a placeholder. Again, only matters if you are sending email.

## A5. Import

Press **Import**. Your new account is created and selected automatically.

> **There is no duplicate check.** Importing the same file twice creates a second account
> with identical settings and no warning. If you do it by accident, delete one on the
> Accounts screen — deleting an account in QualSched changes nothing in Qualtrics.

## A6. Finish the account

![The Accounts screen with a successful connection test](images/04-accounts-connected.png)
*A working account: token stored, data center set, and Qualtrics answering.*

Go to **Accounts** and check the imported settings:

1. **Data center** is filled in.
2. **API token** — if the box shows "Paste your API token" rather than "Stored — type a
   new one to replace it", no token was saved. Paste it now and press **Save**.
3. **Verify TLS certificates** should be ticked. If your file came from the VA's `gov1`
   installation it will be unticked, which is correct for that deployment and only that
   one.
4. Press **Test connection**. You want a green **"Connected. 3 directories visible."** Any
   red message means something above is wrong — fix it before going further.

You now have an account and a survey profile. Continue at
[You're set up](#youre-set-up).

---

# Path B — Set up from scratch

> **This is Path B.** Follow it if you do not have a `config_qualtrics….yaml` file. If one
> turns up, [Path A](#path-a--import-your-existing-setup) is much faster.

Have Qualtrics open in a browser on the **Account Settings → Qualtrics IDs** page — you
will be copying from it.

## B1. Create the account

![The Accounts screen with a successful connection test](images/04-accounts-connected.png)
*A working account: token stored, data center set, and Qualtrics answering.*

Go to **Accounts** and press **+ Add account**. Fill in the *Connection* card:

- **Account name** — anything you will recognise, like `UMN` or `VA`. This is a label for
  you; Qualtrics never sees it.
- **Data center** — the short name from the front of your Qualtrics web address, for
  example `yul1`. Not the whole address, just that piece.
- **API token** — paste it here. It goes into your computer's credential store, not into
  any file.
- **Verify TLS certificates** — leave this ticked. The only reason to turn it off is a
  deployment that inspects encrypted traffic, such as the VA's `gov1` installation.

Press **Save**.

## B2. Point it at your directory and library

In the *Directory and library* card:

- **Contact directory** — press **Load from Qualtrics** at the right of the box and pick
  your directory from the list that appears. If the list will not load, your token or data
  center is wrong.
- **Message library ID** — this one you type or paste by hand, from Qualtrics IDs →
  Libraries. `GR_…` is a shared library, `UR_…` is your personal one.

Press **Save** again.

> **Order matters here.** On the next screen, the mailing-list list cannot load until the
> directory is saved, and the message-template lists cannot load until the library ID is
> saved. If a dropdown refuses to load, this is almost always why.

## B3. Test the connection

Press **Test connection**. A green **"Connected. 3 directories visible."** means the token,
data center and TLS setting all work together.

Do not carry on past a red banner — every screen after this depends on this connection.
[Troubleshooting](#error-messages) lists what each message means.

## B4. Create the survey profile

A survey profile is one study: which survey, which participants, which invitation wording,
and the default schedule. One account can hold several profiles, so a lab with three
studies keeps one account and three profiles.

Go to **Survey profile** and press **+ Add profile**.

### Survey and recipients

![The Survey profile screen with survey, mailing list and templates chosen](images/05-profile-top.png)
*The first two cards. Each dropdown fills itself from Qualtrics once you press Load.*

- **Profile name** — your study's name.
- **Survey** — press **Load from Qualtrics**, pick your survey.
- **Mailing list** — press **Load from Qualtrics**, pick the list holding your
  participants. The list shows how many people are in each one, which is a useful sanity
  check.

> **Why is this a text box and not a menu?** Every one of these starts as a plain text box
> reading "Enter the ID, or load the list above", and only becomes a menu after you press
> **Load from Qualtrics**. That is deliberate: it means you can still type an ID by hand if
> Qualtrics is unreachable, and a saved setting is never silently wiped just because a list
> failed to load.
>
> ![An unloaded dropdown showing its text box and Load link](images/12-dropdown-unloaded.png)

### Invitation templates

- **SMS message** — press **Load from Qualtrics** and pick your SMS template.
- **Email message** — only if you send email, and it must be a template written *as* an
  email. An SMS template will not render properly.

**Preview SMS text** and **Preview email text** show you exactly what participants will
receive. Worth doing once — a template with the wrong survey link is not something you want
to discover after eighty invitations have gone out.

You will notice a note about a short random tag being added to each invitation. Qualtrics
refuses to send two identical messages to the same person on the same day, so QualSched
appends a few random characters to keep them distinct. Participants see it; it is
harmless.

### Survey copies

If your participants get more than one invitation a day, you need this card.

Qualtrics delivers only the **first** invitation for a given survey to a given person each
day. The later ones are not rejected — they are accepted, scheduled, and then quietly
dropped, reporting zero sends. Making the messages different does not help; the limit is on
the survey, not the wording.

The way through is to send each administration of the day through a different survey. Press
**Create N copies** and QualSched clones your survey in Qualtrics as many times as your time
slots need, naming them after the original with `-c1`, `-c2` and so on. The first slot of
each day then uses your original survey, the second uses `-c1`, the third `-c2`, and the
pattern repeats every day.

Three things to know:

- The copies are **real surveys in your Qualtrics account**. Deleting the profile here does
  not remove them.
- **Responses arrive on whichever copy the participant answered.** When you export data, pull
  it from the original *and* every copy, then merge — otherwise most of your day will look
  like missing data.
- **Editing the original later does not change the copies.** If you revise the questionnaire,
  delete the copies in Qualtrics and create them again.

If a profile has fewer copies than it has time slots, the extra slots are skipped when you
compute a plan, and the Schedule screen tells you which ones and why.

### Email sender

![The email sender and scheduling defaults cards](images/06-profile-defaults.png)
*The bottom of the Survey profile screen. These defaults decide what new participants get.*

Skip this card entirely if your study is SMS-only.

If you send email, change all four boxes — **From address**, **From name**, **Reply-to
address**, and **Subject**. They start as `noreply@qualtrics.com` / `Qualtrics` /
`Survey`, which is not what you want participants to see.

### Scheduling defaults

These are the values given to participants who do not have their own. They never overwrite
anything a participant already has.

| Box | What it means |
| --- | --- |
| **Time zone** | The zone used for participants who have not specified one. An IANA name like `America/Chicago`. |
| **Link expires after (minutes)** | How long a survey link stays usable after it arrives. 60 is typical. |
| **Contact method** | SMS or email. |
| **Start date** | The first day of the schedule. |
| **Number of days** | How many consecutive days each participant runs for. |
| **Time slots** | What times of day to prompt. See [How to write time slots](#how-to-write-time-slots). |

**Number of days starts at 0, and 0 means nobody is scheduled.** Set it before your first
send.

Press **Save**. If the Time slots box is invalid, Save stays greyed out and a red note
explains what is wrong.

You now have an account and a survey profile. Continue at
[You're set up](#youre-set-up).

---

# You're set up

Both paths end here. Contacts, Schedule and Distributions are no longer greyed out, and
the bottom-left corner shows your account and profile.

## Three things to check before your first send

These trip up almost everyone, whichever path you took.

**1. Number of days is 0 out of the box.** A profile you built from scratch starts at 0,
and old config files almost always carry 0 as well. Zero means *no invitations*, so every
participant shows as skipped with "NumDays is 0 or unset". Fix it on **Survey profile** →
Scheduling defaults for new participants, and on **Contacts** for people already in the
list.

**2. Start date is blank or stale.** A new profile has no start date; an imported one has
whatever date the study started, often years ago. A start date in the past is not an
error, but every slot before now is silently dropped, so you can end up sending nothing
and wondering why.

**3. The email sender is still a placeholder.** If you send email, check the *Email
sender* card really says your address and not `noreply@qualtrics.com`. SMS-only studies can
ignore this.

## Do a rehearsal first

Before real participants are involved, send yourself one invitation. It exercises every
screen in order and catches setup problems in the order they would otherwise bite you.

1. **Contacts** → **+ Add participant**. Put in your own name and your own mobile number
   with its country code, for example `16125551234`.
2. In the Scheduling section, set **Number of days** to `1`, **Time slots** to a single
   time about fifteen minutes from now — if it is 2:10pm, use `1425` — and leave
   everything else blank so it picks up your profile defaults.
3. Press **Add to mailing list**. Your row should show a green **ready** badge. If it says
   skipped, the reason underneath tells you what to fix, and
   [Troubleshooting](#skipped--what-each-reason-means) explains each one.
4. **Schedule** → **Compute plan**. You should see exactly one invitation, at the time you
   chose, in your time zone.
5. Press **Send 1 invitations** and confirm.
6. **Distributions** → **Load**. Your invitation should be listed as `scheduled`.
7. Wait for the text to arrive. Open the link and check the survey looks right.
8. Clean up: on **Distributions**, tick the row and press **Cancel selected** if it has not
   sent yet. Then on **Contacts**, press **Remove** on your own row.

If the message arrives and the link works, your setup is sound.

---

# Everyday use: sending invitations

Once you are set up, the routine is short: open **Contacts** and check everyone is ready,
go to **Schedule** and press **Compute plan**, read the preview, then **Send**. Check
**Distributions** afterwards if you want proof.

The rest of this section is that loop in detail.

## Step 1 — Review the participant list

![The Contacts screen showing ready and skipped participants](images/07-contacts-list.png)
*Everyone in the mailing list, their scheduling values, and whether each is ready.*

**Contacts** shows everybody in your mailing list. Names read "Last, First". Every column
header is clickable to sort by it — click again to reverse.

The columns after Phone and Email are the scheduling fields stored in Qualtrics. They keep
their Qualtrics names on purpose, so they match what you would see there.

Top right, **"3 of 6 ready to schedule"** is the number that matters. Each row carries a
green **ready** badge or a grey **skipped** one with the reason printed underneath.

> **Only the first problem is shown.** QualSched stops at the first thing wrong with a
> participant, so fixing one reason can reveal another. That is not the app inventing new
> errors — it is working through a list.

Press **Refresh** to re-read from Qualtrics if a colleague has been editing the list.

## Step 2 — Add or edit a participant

![The participant editor open in edit mode](images/11-contact-editor.png)
*Who they are, and when they should be prompted.*

**+ Add participant**, or **Edit** on any row.

*Who they are* needs at least one of name, email address or phone number. Phone numbers
need the country code.

*Scheduling* holds that person's own values. **When adding, leave a box blank to use the
profile default** — that is usually what you want, so most new participants only need a
name and a phone number. When editing, only the boxes you actually change are written
back.

## Step 3 — Fill gaps in bulk

**Fill in missing values** applies your profile's defaults to several people at once.

**Tick the checkboxes on the rows you want first** — the button does nothing and stays
greyed out until at least one row is selected. This is the single most common place people
get stuck.

> **It only fills in values a participant is missing.** If someone already has
> `NumDays` set to `0`, that is a value, so this button will not change it. The most common
> problem is therefore not fixed by the most obvious button. To fix a `NumDays` of `0` you
> have to edit each participant, or change it in the mailing list in Qualtrics.

## Step 4 — Compute the plan

Go to **Schedule** and press **Compute plan**. Nothing is sent.

![The Schedule screen showing a computed plan](images/08-schedule-preview.png)
*Every invitation that would go out, with the exact moment each one arrives.*

If you use random time windows, **the actual times are drawn now**, and those exact times
are what gets sent. Computing twice legitimately gives two different sets of times.

## Step 5 — Read the preview

The table has one row per invitation: who, what number or address, SMS or email, which day,
which slot, the local time in *their* time zone, the same moment in UTC, and when the link
expires.

Underneath, two more cards appear when relevant:

![The skipped participants and dropped times cards](images/13-schedule-skipped.png)

- **"N participant(s) skipped"** — people who get nothing, and why.
- **"N individual time(s) dropped"** — individual moments that have already passed. An
  invitation booked for a past moment is accepted by Qualtrics and then never delivered, so
  QualSched drops it and tells you instead.

Anything you fix means computing the plan again — the preview does not update itself.

## Step 6 — Send

Press **Send N invitations** and confirm. A progress bar counts through them; a large study
takes a few minutes, because QualSched deliberately paces the requests to stay inside
Qualtrics' rate limits.

![A successful send](images/09-schedule-result.png)

A green banner means everything went through. If some failed, a table lists which and why —
the rest still went out, so fix the cause and compute a fresh plan for what is left.

> **If you see a yellow "Needs attention" banner**, read it. It means invitations were sent
> but QualSched could not record that fact against those participants. Until you set their
> **Surveys scheduled** by hand on the Contacts screen to the number they received, a later
> run will schedule them a second time and they will get double the prompts.

## Step 7 — Confirm on Distributions

![The Distributions screen listing booked invitations](images/10-distributions.png)
*Everything already booked with Qualtrics, and anything still cancellable.*

Choose **SMS** or **Email** and press **Load**. **Not yet sent only** is ticked by default,
so you see what is still to come.

Each row shows the send time twice: in the participant's own time zone, and in UTC. Two
people in different time zones will show the same UTC time with different local times —
that is correct, not a bug.

The badge reads `scheduled` for invitations still in the future and `sent` for ones already
delivered. Anything still `scheduled` can be cancelled.

---

# Common tasks

### A participant drops out

1. **Distributions** → **Load**, tick their remaining invitations, **Cancel selected**.
2. **Contacts** → **Edit** them → set **Number of days** to `0` so they are not picked up
   again.

Or use **Remove** on the Contacts screen to do both at once — see below.

### Someone needs re-scheduling after being scheduled already

Once a participant has been scheduled, their **Surveys scheduled** field is non-zero and
they are skipped from then on. That is deliberate: it is what stops a second run from
double-booking everyone.

To schedule them again:

1. **Distributions** → cancel any invitations they still have pending.
2. **Contacts** → **Edit** → set **Surveys scheduled** back to `0`, and set a fresh
   **Start date**.
3. **Schedule** → **Compute plan** → **Send**.

> **Cancelling on the Distributions screen does not reset Surveys scheduled.** You have to
> zero it yourself in step 2, or they stay skipped forever.

### Add a participant mid-study

**Contacts** → **+ Add participant**, with a **Start date** of today or later. Then compute
and send as usual — everyone already scheduled is skipped automatically, so only the new
person is booked.

### Remove someone entirely

**Contacts** → **Remove**. This cancels any invitations they have pending, then takes them
out of this study's mailing list. They stay in your Qualtrics directory, and any survey
responses they have already submitted are untouched.

If some invitations cannot be cancelled, QualSched leaves the person in the list and says
so, rather than orphaning invitations nobody can trace.

### Change the time slots for everyone

Changing **Time slots** on the Survey profile only affects participants who have no value
of their own — which, in an established study, is nobody. To change existing participants
you must edit each one, or edit the mailing list in Qualtrics directly.

Changing the slots does not affect invitations already booked. Cancel those first on
Distributions if you want the new pattern to apply.

### Switch between studies or accounts

Pick a different profile in the list on the **Survey profile** screen, or a different
account on the **Accounts** screen. The bottom-left corner always shows where you are.

---

# Reference: the scheduling fields

Each participant carries these in Qualtrics. Your profile's defaults fill in whatever is
missing.

| Field | What it does | If it is wrong |
| --- | --- | --- |
| **StartDate** | First day of the schedule, `YYYY-MM-DD` | Blank skips the person; a past date means past slots are dropped |
| **NumDays** | How many consecutive days | `0` skips the person entirely |
| **TimeSlots** | What times of day | Invalid text skips the person, with an explanation |
| **TimeZone** | Which zone the times mean | Blank falls back to the profile's; an unrecognised name skips the person |
| **ContactMethod** | `sms` or `email` | Anything else skips the person |
| **ExpireMinutes** | How long the link stays usable | Blank falls back to the profile's, normally 60 |
| **SurveysScheduled** | How many invitations they have had | Anything other than `0` skips them |

**SurveysScheduled is the safety catch.** QualSched writes it after sending, and any
non-zero value means "already done, leave alone". It is what makes it safe to press Send
twice by mistake.

You will also see a **Delete unsent** box in the participant editor. Nothing reads it —
leave it alone. The **Remove** button is what actually cancels pending invitations.

## How to write time slots

Times are 24-hour, written without a colon: `800` is 8:00am, `1430` is 2:30pm, `2000` is
8:00pm.

| What you type | What happens |
| --- | --- |
| `800,1200,1600,2000` | Four invitations a day, at those exact times |
| `[800,900]` | One invitation at a random minute between 8:00 and 9:00 |
| `800,[1200,1300],2000` | Mixed — two fixed times and one random window |
| `[2350,0010]` | A window crossing midnight; it lands on the next day |

Random windows are the point of EMA: a participant who knows the prompt comes at exactly
8:00 starts behaving differently. The window is redrawn every time you compute a plan.

Hours must be 23 or below and minutes 59 or below, so `2400` and `870` are both rejected.
The Survey profile screen checks as you type and will not let you save something invalid.

## Time zones and daylight saving

Times mean whatever the clock says where the participant is. A participant in
`America/New_York` and one in `America/Los_Angeles` with the same `800` slot get prompted
three hours apart in real time, which is what you want.

Use full IANA names — `America/Chicago`, `Europe/London`, `Asia/Tokyo` — not abbreviations
like `CST`.

Daylight saving is handled. On the spring weekend, a slot at a time that does not exist
moves forward to the first real minute. On the autumn weekend, a time that happens twice
uses the earlier one.

## Why a slot can vanish

Any moment already in the past — or less than a minute away — is dropped rather than
booked, and listed in the preview with a reason. Qualtrics accepts invitations dated in the
past and then never delivers them, so booking one would look like success and produce
nothing.

This is why a start date from last month produces far fewer invitations than you expect.

---

# Troubleshooting

## "Skipped" — what each reason means

QualSched stops at the first problem, so fixing one can reveal the next.

### Shown on the Contacts screen

| Reason | What it means | Fix |
| --- | --- | --- |
| `already scheduled (SurveysScheduled = 12)` | They have had their invitations | Set Surveys scheduled to `0` if you genuinely want to schedule them again |
| `NumDays is 0 or unset` | No days to schedule | Set Number of days above 0 |
| `no ContactMethod and UseSMS is not 1` | No delivery method | Set Contact method to `sms` or `email` |
| `ContactMethod "text" is not 'sms' or 'email'` | Misspelled method | It must be exactly `sms` or `email` |
| `TimeSlots invalid: …` | The times will not parse | See [How to write time slots](#how-to-write-time-slots) |
| `TimeN fields invalid: …` | Older `Time1`, `Time2` fields will not parse | Same rules; each must be a plain time like `800` |
| `no time slots set` | Empty time slots | Give them at least one time |
| `StartDate is not set` | No start date | Set one, today or later |
| `StartDate "03/16/24" is not a YYYY-MM-DD date` | Wrong date format | Write it as `2026-03-16` |
| `unknown timezone "CST" …` | Not an IANA zone name | Use `America/Chicago` rather than `CST` |

### Only shown after Compute plan

These three cannot be detected until the plan is worked out, so a participant can show a
green **ready** badge on Contacts and still be skipped here.

| Reason | What it means | Fix |
| --- | --- | --- |
| `no phone number on record` | Set to SMS but has no phone number | Add one with its country code, or switch them to email |
| `no email address on record` | Set to email but has no address | Add one, or switch them to SMS |
| `all 4 slots dropped (…)` | Every one of their times has already passed | Move their start date forward |

## Error messages

| Message | Cause | Fix |
| --- | --- | --- |
| `No API token stored for this account.` | No token saved | Accounts → paste the token → Save |
| `Qualtrics rejected the API token (401).` | Wrong token, or right token with the wrong data center | Check both. A token from one data center will not work on another |
| `Qualtrics rate limit hit (429).` | Too many requests too quickly | Wait a minute and retry. Anything already sent stays sent |
| `Keychain error: … needs a running Secret Service` | Linux only: no keyring running | Install and start `gnome-keyring` or `kwallet`. QualSched cannot store your token without one |
| `config.json was written by a newer version of QualSched` | Your settings came from a newer version | Update QualSched |
| `Invalid Content-Type` or other Qualtrics errors | Passed through from Qualtrics verbatim | The wording comes from Qualtrics; searching their documentation for it usually helps |

## Things that look wrong but are not

**Two Compute plan runs give different times.** Expected, if you use random windows. The
times are drawn fresh each time, and the ones you see are the ones that get sent.

**A dropdown shows "SV_abc123 (not in list)".** The saved ID is not in what Qualtrics
returned — usually because the survey was deleted or lives in another account. QualSched
keeps it visible rather than silently clearing your setting.

**A dropdown is a plain text box.** It becomes a menu after you press **Load from
Qualtrics**. If loading fails, you can still type the ID.

**A dropdown shows something you just deleted in Qualtrics.** Lists are remembered for five
minutes to avoid hammering the API. Press **Load from Qualtrics** again, or wait.

**Someone still says "already scheduled" after you cancelled their invitations.** Cancelling
does not reset Surveys scheduled. Set it to `0` on the Contacts screen.

**Two rows on Distributions show the same UTC time but different local times.** Correct —
they are in different time zones.

## Where your settings and token live

| Platform | Settings file |
| --- | --- |
| Linux | `~/.config/com.lnpi.qualsched/config.json` |
| macOS | `~/Library/Application Support/com.lnpi.qualsched/config.json` |
| Windows | `%APPDATA%\com.lnpi.qualsched\config.json` |

**Your API token is not in that file.** It lives in your operating system's credential
store — Windows Credential Manager, macOS Keychain, or the Linux keyring. That means the
settings file is safe to copy to another machine, but you will re-enter the token there.

Everything about *participants* lives in Qualtrics, not on your computer, so a colleague
with access to the same mailing list sees the same schedules.

## If nothing else works

Send whoever supports your study:

- What you were doing, and what you expected instead.
- The exact text of any error message — a screenshot of the whole window is ideal.
- The version number from the bottom of the sidebar.
- Whether **Test connection** on the Accounts screen succeeds.

---

<details>
<summary><strong>Appendix — screenshot checklist (maintainers)</strong></summary>

The images above are referenced but may not all exist yet. Capture them into
`docs/images/` using exactly these filenames.

**Before capturing anything:** use invented participant names, `555` phone numbers and
`example.com` addresses. This application handles human-subjects data, and a real
participant's name in a repository screenshot is a reportable disclosure. Prefer a demo
Qualtrics account so directory, survey and library IDs in shot are not production
identifiers.

Use one window size throughout (about 1280×900), save as PNG, and crop to the application
window or to the named card — no desktop, no other windows.

| File | What to capture |
| --- | --- |
| `01-first-launch.png` | The app with no account at all. Contacts, Schedule and Distributions greyed out; footer reads "No account selected" |
| `02-import-choose-files.png` | Import screen, "1. Choose the files" card, both paths filled in, before pressing Read config |
| `03-import-review.png` | Import screen, "2. Check what was found" — the four editable boxes, the whole read-only table, and the warnings banner with 3+ warnings, all in one tall shot |
| `04-accounts-connected.png` | Accounts screen: Connection card, Directory and library card, the button row, and the green "Connected. N directories visible." banner. Token field showing "Stored — type a new one to replace it" |
| `05-profile-top.png` | Survey profile: profile list at left, "Survey and recipients" and "Invitation templates" cards with all four dropdowns loaded and selected |
| `06-profile-defaults.png` | Same screen scrolled down: "Email sender" with real values (not the `noreply@` defaults) and "Scheduling defaults" with a valid Time slots and a non-zero Number of days |
| `07-contacts-list.png` | 5–6 rows with one `ready` badge and two *different* `skipped` reasons visible; two rows ticked so the button reads "Fill in missing values (2)"; the "3 of 6 ready to schedule" counter in frame |
| `08-schedule-preview.png` | After Compute plan: the "N invitations for M participant(s)" heading, about 8 rows showing all eight columns, and the Send button in frame |
| `09-schedule-result.png` | The green "Scheduled 12 invitation(s)." result with "Everything went through." |
| `10-distributions.png` | SMS loaded, "Not yet sent only" ticked, several `scheduled` badges, one row selected so the button reads "Cancel selected (1)" |
| `11-contact-editor.png` | The participant editor in **edit** mode, both "Who they are" and "Scheduling" grids fully visible |
| `12-dropdown-unloaded.png` | Tight crop of one dropdown in its unloaded state: the text box reading "Enter the ID, or load the list above" with the "Load from Qualtrics" link |
| `13-schedule-skipped.png` | Schedule screen scrolled to show the "N participant(s) skipped" and "N individual time(s) dropped" cards together |

`14-needs-attention.png` (the yellow bookkeeping-failure banner) is referenced in prose but
not linked as an image, since it is hard to produce deliberately. Capture it
opportunistically if you ever see one.

</details>
