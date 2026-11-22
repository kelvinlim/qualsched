# Qualtrics Contact Frequency and SMS Duplicate Limits

This document captures Qualtrics' official contact-frequency rules and the separate SMS duplicate-blocking behavior. It exists so QualSched maintainers do not have to rediscover these rules each time a field issue arises.

The **one-invitation-per-day** constraint described in the [User Guide](USER_GUIDE.md#more-than-one-invitation-a-day) is the user-facing summary. This document is the technical detail underneath.

## Official Qualtrics contact-frequency rules

Source: [Qualtrics Contact Frequency Rules](https://www.qualtrics.com/support/iq-directory/directory-settings-tab/contact-frequency-rules/)

XM Directory contact frequency rules live under **Directory settings → Contact frequency**. Setting or editing them requires Brand Admin or Manage Directory permissions.

### What directory rules do

Directory-level rules can:
- Require a minimum number of days between messages (any channel)
- Cap how many messages a contact can receive in a timeframe

These rules apply to:
- Survey invitations
- SMS invitations
- Other message types listed in the Qualtrics documentation

Directory rules apply to SMS invitations but **not** to SMS reminders.

### Custom frequency rules

Custom rules target either:
- A specific mailing list, or
- A specific survey

They cannot mix both in one rule.

One available option is:

> **Always allow contacts in the selected list(s) to receive messages, surveys, and intercepts regardless of directory rules**

This override exempts the selected mailing list from directory contact-frequency limits **only**. It does not override the duplicate-block behavior described below.

### Distribution outcomes

When contact-frequency rules block a send, Qualtrics still creates the distribution record. The excess messages are marked **Skipped** in distribution metrics.

**Skipped** = contact frequency rules blocked the send.

**Duplicates** = duplicate-avoidance rules blocked the send (see below).

These are different.

## Duplicate-blocking behavior (separate from frequency rules)

Qualtrics always blocks duplicates, independent of any directory frequency rule.

### Email duplicate definition

From the [Contact Frequency Rules](https://www.qualtrics.com/support/iq-directory/directory-settings-tab/contact-frequency-rules/) page:

> A duplicate email is defined as the same subject and body sent to the same email address within 12 hours.

### SMS duplicate definition

From the [SMS Surveys](https://www.qualtrics.com/support/survey-platform/distributions-module/mobile-distributions/sms-surveys/) documentation:

> A duplicate SMS invitation is defined as the same invitation message sent to the same phone number within 24 hours.

The "Always allow" frequency exception does **not** override this duplicate block. Even a mailing list exempted from frequency caps will still be subject to the 24-hour SMS duplicate rule.

### 2-way SMS exception

2-way SMS is exempt from the duplicate-invitation rule, but 2-way SMS is a different Qualtrics product. Questions are delivered in the SMS thread itself, the session stays open for 48 hours, and responses arrive as SMS. QualSched uses the standard EMA survey-link path (a URL sent via SMS that opens the survey in a browser), not 2-way SMS, so this exception does not apply.

## Observed field behavior (not official Qualtrics documentation)

These observations come from real deployments and support tickets. They are consistent with the official documentation above but include detail Qualtrics has not published.

### UMN TDX ticket 2678655 (Jul–Aug 2026)

**Participants:** Abbey Hammell / Abbie Beekman  
**Survey:** EMA-PTSD+MDD (`SV_6Wi45DRitHabm7k`) on `umn.qualtrics.com`  
**Mailing list:** `ptsd_mailing_list` (display name), `CG_31ZPX5GMG2FKZoA` (technical ID)  
**Directory pool:** `POOL_3fAZGWRVfLKuxe3`

UMN confirmed they have no extra per-day SMS *count* cap they can raise. They described the 24-hour same-body SMS block as the limiting factor.

On Jul 29, 2026, SMS invitations on that survey showed status **Failed** with **Duplicates = 1** for the second SMS sent to a contact that day. An "Always allow" frequency exception would **not** have unblocked these sends — the duplicate rule is separate.

### QualSched workaround attempts

**QualSched 0.1.4** tried survey copies (`-c1`, `-c2`, …) to deliver multiple invitations per day by routing each to a different survey. This failed in the field. The duplicate block still applied because the invitation message body was the same, even though the survey ID differed.

**QualSched 0.1.5** books the full plan but warns when multiple invitations per day are requested. README already documents that "Qualtrics delivers only the first invitation for a given survey to a given person each day." This is inferred from field behavior. Qualtrics has not published official documentation that explicitly defines "first invitation per survey per person per day," but this is the observable outcome.

### Message randomization

Kelvin already implemented `decorate_message` in QualSched, which appends a random `[xx0xx0xx]` tag to each SMS body. This ensures that successive messages to the same contact differ in content. The distribution creation POSTs `messageText` with this randomized body.

This approach works around the 12-hour email duplicate rule and previously worked around the 24-hour SMS duplicate rule at some Qualtrics brands.

### VA brand behavior

The VA Qualtrics brand (`gov1` data center) used to accept up to 4 SMS per day when the message body changed (i.e., `decorate_message` randomization was sufficient). Kelvin reports this stopped working recently — the duplicate block now applies even with randomized bodies at VA.

This suggests Qualtrics may have changed the duplicate-detection logic at certain brands, or that additional rate limits exist beyond the documented 24-hour SMS duplicate rule. No official documentation for this change has been located.

## Implications for QualSched

1. **Survey copies do not bypass duplicate blocks.** The `SurveyID` parameter does not change the SMS body, so invitations are still duplicates under Qualtrics rules.

2. **Message randomization is necessary but not sufficient.** It prevents duplicate blocks when Qualtrics compares message text, but some brands now block duplicates by other criteria (recipient + survey + time window, for example).

3. **"Always allow" frequency exceptions do not help.** They override directory caps (e.g., "no more than 5 messages per week") but not the duplicate rule.

4. **Multiple invitations per day remain unsupported in the general case.** QualSched warns when a plan requests this, and the first invitation usually succeeds while the rest report zero sends or Duplicates = 1.

5. **Qualtrics Support is the only escalation path.** If a study design requires multiple SMS per day, the study coordinator must ask Qualtrics Support what options exist for their specific brand and directory before enrolling participants. QualSched cannot work around brand-level rate limits.

## References

- [Qualtrics Contact Frequency Rules](https://www.qualtrics.com/support/iq-directory/directory-settings-tab/contact-frequency-rules/)
- [Qualtrics SMS Surveys](https://www.qualtrics.com/support/survey-platform/distributions-module/mobile-distributions/sms-surveys/)
- UMN TDX ticket 2678655 (internal)
- QualSched CHANGELOG and README sections on survey copies and multiple-per-day warnings
