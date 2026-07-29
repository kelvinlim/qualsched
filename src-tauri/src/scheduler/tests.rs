use super::*;
use chrono::TimeZone;
use rand::{rngs::StdRng, SeedableRng};

fn rng() -> StdRng {
    StdRng::seed_from_u64(0xC0FFEE)
}

fn embedded(pairs: &[(&str, &str)]) -> BTreeMap<String, String> {
    pairs
        .iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect()
}

fn defaults() -> EligibilityDefaults<'static> {
    EligibilityDefaults {
        timezone: DEFAULT_TIMEZONE,
        minutes_expire: 60,
    }
}

/// A rotation of `n` surveys: the original plus `n - 1` copies, as a profile with enough
/// copies would produce. Leaked so it can sit in a `PlanInputs` without the caller
/// having to keep a binding alive.
fn surveys(n: usize) -> &'static [SurveyRef] {
    let list: Vec<SurveyRef> = (0..n)
        .map(|i| SurveyRef {
            id: if i == 0 {
                "SV_original".to_string()
            } else {
                format!("SV_copy{i}")
            },
            label: if i == 0 {
                "original".to_string()
            } else {
                format!("c{i}")
            },
        })
        .collect();
    Box::leak(list.into_boxed_slice())
}

/// Defaults to exactly enough surveys for the slots given, so tests that predate
/// rotation keep their original shape.
fn plan_inputs<'a>(slots: &'a [Slot], start: &'a str, num_days: i64) -> PlanInputs<'a> {
    PlanInputs {
        contact_id: "CID_1",
        contact_name: "Test Participant",
        destination: "+15555550100",
        method: Method::Sms,
        slots,
        surveys: surveys(slots.len()),
        num_days,
        start_date: start,
        timezone: "America/Chicago",
        expire_minutes: 60,
    }
}

// --- parsing ---------------------------------------------------------------

#[test]
fn parses_plain_slot_list() {
    let slots = parse_time_slots("800,1200,1600,2000").unwrap();
    assert_eq!(
        slots,
        vec![
            Slot::Fixed(800),
            Slot::Fixed(1200),
            Slot::Fixed(1600),
            Slot::Fixed(2000)
        ]
    );
}

#[test]
fn parses_windows_and_mixed_lists() {
    assert_eq!(
        parse_time_slots("[800,900],[2000,2100]").unwrap(),
        vec![Slot::Window(800, 900), Slot::Window(2000, 2100)]
    );
    assert_eq!(
        parse_time_slots(" 800 , [1200,1300] ,2000 ").unwrap(),
        vec![Slot::Fixed(800), Slot::Window(1200, 1300), Slot::Fixed(2000)]
    );
}

#[test]
fn rejects_malformed_slots() {
    // 2366 is the exact value the CLI's eval-based parser accepted and then crashed on.
    assert!(parse_time_slots("2366").is_err());
    assert!(parse_time_slots("2500").is_err());
    assert!(parse_time_slots("[800]").is_err());
    assert!(parse_time_slots("[800,900").is_err());
    assert!(parse_time_slots("eight").is_err());
}

#[test]
fn reads_time_n_fields_in_order() {
    let e = embedded(&[
        ("Time1", "800"),
        ("Time2", "1200"),
        ("Time3", "2000"),
        ("TimeZone", "America/Chicago"),
    ]);
    assert_eq!(
        slots_from_time_n(&e).unwrap(),
        vec![Slot::Fixed(800), Slot::Fixed(1200), Slot::Fixed(2000)]
    );
}

// --- slot resolution -------------------------------------------------------

#[test]
fn fixed_slot_resolves_literally() {
    let r = resolve_slot(Slot::Fixed(830), &mut rng());
    assert_eq!(r, ResolvedTime { minutes: 8 * 60 + 30, extra_days: 0 });
}

#[test]
fn window_stays_within_bounds() {
    let mut rng = rng();
    for _ in 0..500 {
        let r = resolve_slot(Slot::Window(800, 900), &mut rng);
        assert_eq!(r.extra_days, 0);
        assert!((480..=540).contains(&r.minutes), "got {}", r.minutes);
    }
}

#[test]
fn midnight_crossing_window_wraps_and_carries_the_day() {
    let mut rng = rng();
    let mut saw_before = false;
    let mut saw_after = false;
    for _ in 0..1000 {
        let r = resolve_slot(Slot::Window(2350, 10), &mut rng);
        let late = (1430..=1439).contains(&r.minutes); // 23:50-23:59
        let early = r.minutes <= 10; // 00:00-00:10
        assert!(late || early, "got {} minutes", r.minutes);
        if late {
            assert_eq!(r.extra_days, 0);
            saw_before = true;
        } else {
            assert_eq!(r.extra_days, 1, "post-midnight time must advance the day");
            saw_after = true;
        }
    }
    assert!(saw_before && saw_after, "window should span both sides of midnight");
}

// --- timezone / DST --------------------------------------------------------

#[test]
fn converts_local_to_utc_across_dst() {
    let slots = [Slot::Fixed(800)];
    let now = Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap();

    // CST: UTC-6, so 08:00 local is 14:00Z.
    let (winter, _) = build_contact_plan(&plan_inputs(&slots, "2026-01-15", 1), now, &mut rng());
    assert_eq!(winter[0].send_utc.format("%H:%M").to_string(), "14:00");

    // CDT: UTC-5, so 08:00 local is 13:00Z.
    let (summer, _) = build_contact_plan(&plan_inputs(&slots, "2026-07-15", 1), now, &mut rng());
    assert_eq!(summer[0].send_utc.format("%H:%M").to_string(), "13:00");
}

#[test]
fn spring_forward_gap_advances_to_a_valid_time() {
    // 2026-03-08, 02:30 America/Chicago does not exist.
    let slots = [Slot::Fixed(230)];
    let now = Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap();
    let (items, skipped) =
        build_contact_plan(&plan_inputs(&slots, "2026-03-08", 1), now, &mut rng());
    assert!(skipped.is_empty(), "should resolve, not skip: {skipped:?}");
    assert_eq!(items.len(), 1);
    let local = items[0].send_utc.with_timezone(&"America/Chicago".parse::<Tz>().unwrap());
    assert_eq!(local.format("%H:%M").to_string(), "03:00");
}

#[test]
fn fall_back_ambiguity_picks_the_earlier_instant() {
    // 2026-11-01, 01:30 America/Chicago occurs twice (CDT then CST).
    let slots = [Slot::Fixed(130)];
    let now = Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap();
    let (items, _) = build_contact_plan(&plan_inputs(&slots, "2026-11-01", 1), now, &mut rng());
    assert_eq!(items.len(), 1);
    // Earlier instant is the CDT one: 01:30 CDT == 06:30Z (CST would be 07:30Z).
    assert_eq!(items[0].send_utc.format("%H:%M").to_string(), "06:30");
}

#[test]
fn unknown_timezone_is_skipped_not_panicked() {
    let slots = [Slot::Fixed(800)];
    let mut input = plan_inputs(&slots, "2026-07-15", 1);
    input.timezone = "Mars/Olympus";
    let now = Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap();
    let (items, skipped) = build_contact_plan(&input, now, &mut rng());
    assert!(items.is_empty());
    assert!(skipped[0].reason.contains("unknown timezone"));
}

// --- plan shape ------------------------------------------------------------

#[test]
fn expands_days_times_slots() {
    let slots = [Slot::Fixed(800), Slot::Fixed(1200), Slot::Fixed(2000)];
    let now = Utc.with_ymd_and_hms(2026, 6, 1, 0, 0, 0).unwrap();
    let (items, skipped) =
        build_contact_plan(&plan_inputs(&slots, "2026-07-01", 4), now, &mut rng());
    assert_eq!(items.len(), 12);
    assert!(skipped.is_empty());
    assert_eq!(items.iter().filter(|i| i.day_index == 3).count(), 3);
}

// Qualtrics drops a second invitation for the same survey to the same contact on the
// same day, so each slot of a day has to name a different survey.
#[test]
fn each_slot_of_a_day_uses_its_own_survey_and_repeats_across_days() {
    let slots = [Slot::Fixed(800), Slot::Fixed(1200), Slot::Fixed(2000)];
    let now = Utc.with_ymd_and_hms(2026, 6, 1, 0, 0, 0).unwrap();
    let (items, skipped) =
        build_contact_plan(&plan_inputs(&slots, "2026-07-01", 4), now, &mut rng());

    assert!(skipped.is_empty());
    for day in 0..4 {
        let labels: Vec<&str> = items
            .iter()
            .filter(|i| i.day_index == day)
            .map(|i| i.survey_label.as_str())
            .collect();
        assert_eq!(
            labels,
            ["original", "c1", "c2"],
            "day {day} should walk the rotation in slot order"
        );
    }
    let day0: Vec<&str> = items
        .iter()
        .filter(|i| i.day_index == 0)
        .map(|i| i.survey_id.as_str())
        .collect();
    assert_eq!(day0.len(), day0.iter().collect::<std::collections::HashSet<_>>().len());
}

#[test]
fn slots_past_the_end_of_the_rotation_are_skipped_not_reused() {
    let slots = [
        Slot::Fixed(800),
        Slot::Fixed(1200),
        Slot::Fixed(1600),
        Slot::Fixed(2000),
    ];
    let mut input = plan_inputs(&slots, "2026-07-01", 2);
    input.surveys = surveys(2); // original + c1, for four slots a day
    let now = Utc.with_ymd_and_hms(2026, 6, 1, 0, 0, 0).unwrap();
    let (items, skipped) = build_contact_plan(&input, now, &mut rng());

    assert_eq!(items.len(), 4, "two sendable slots on each of two days");
    assert_eq!(skipped.len(), 4);
    assert!(skipped
        .iter()
        .all(|s| s.reason.contains("no survey to send through")));
    assert!(items
        .iter()
        .all(|i| i.survey_label == "original" || i.survey_label == "c1"));
}

// A dropped early slot must not slide the later slots onto the wrong survey.
#[test]
fn dropping_a_past_slot_leaves_the_rotation_in_place() {
    let slots = [Slot::Fixed(800), Slot::Fixed(2000)];
    let now = Utc.with_ymd_and_hms(2026, 7, 15, 18, 0, 0).unwrap(); // 13:00 CDT on day 0
    let (items, _) = build_contact_plan(&plan_inputs(&slots, "2026-07-15", 2), now, &mut rng());

    let day0: Vec<&str> = items
        .iter()
        .filter(|i| i.day_index == 0)
        .map(|i| i.survey_label.as_str())
        .collect();
    assert_eq!(day0, ["c1"], "the surviving 20:00 slot keeps slot 2's survey");
}

// The wrapped send lands on the next calendar day but keeps its slot's survey.
#[test]
fn a_midnight_crossing_window_keeps_its_positional_survey() {
    let slots = [Slot::Window(2350, 10), Slot::Fixed(800)];
    let now = Utc.with_ymd_and_hms(2026, 6, 1, 0, 0, 0).unwrap();
    let (items, _) = build_contact_plan(&plan_inputs(&slots, "2026-07-01", 1), now, &mut rng());

    let wrapped = items
        .iter()
        .find(|i| i.slot_label.starts_with('['))
        .expect("the window slot should produce an item");
    assert_eq!(wrapped.survey_label, "original");
}

#[test]
fn skips_past_slots_and_reports_them() {
    // "Now" sits midway through the schedule: day 0 is gone, day 1 remains.
    let slots = [Slot::Fixed(800), Slot::Fixed(2000)];
    let now = Utc.with_ymd_and_hms(2026, 7, 15, 18, 0, 0).unwrap(); // 13:00 CDT on day 0
    let (items, skipped) =
        build_contact_plan(&plan_inputs(&slots, "2026-07-15", 2), now, &mut rng());

    assert_eq!(items.len(), 3, "only the 08:00 slot on day 0 is past");
    assert_eq!(skipped.len(), 1);
    assert!(skipped[0].reason.contains("in the past"));
    assert!(items.iter().all(|i| i.send_utc > now));
}

#[test]
fn expiration_follows_send_time() {
    let slots = [Slot::Fixed(800)];
    let mut input = plan_inputs(&slots, "2026-07-15", 1);
    input.expire_minutes = 45;
    let now = Utc.with_ymd_and_hms(2026, 6, 1, 0, 0, 0).unwrap();
    let (items, _) = build_contact_plan(&input, now, &mut rng());
    assert_eq!(items[0].expire_utc - items[0].send_utc, Duration::minutes(45));
}

// --- eligibility -----------------------------------------------------------

#[test]
fn eligible_contact_reads_all_fields() {
    let e = embedded(&[
        ("SurveysScheduled", "0"),
        ("NumDays", "5"),
        ("ContactMethod", "sms"),
        ("TimeSlots", "800,1200"),
        ("StartDate", "2026-07-15"),
        ("TimeZone", "America/New_York"),
        ("ExpireMinutes", "90"),
    ]);
    match contact_eligibility(&e, &defaults()) {
        Eligibility::Eligible {
            method,
            slots,
            num_days,
            timezone,
            expire_minutes,
            ..
        } => {
            assert_eq!(method, Method::Sms);
            assert_eq!(slots.len(), 2);
            assert_eq!(num_days, 5);
            assert_eq!(timezone, "America/New_York");
            // Reads ExpireMinutes rather than falling through to 60 as the CLI did.
            assert_eq!(expire_minutes, 90);
        }
        other => panic!("expected eligible, got {other:?}"),
    }
}

#[test]
fn contact_method_overrides_use_sms() {
    let e = embedded(&[
        ("SurveysScheduled", "0"),
        ("NumDays", "1"),
        ("ContactMethod", "email"),
        ("UseSMS", "1"),
        ("TimeSlots", "800"),
        ("StartDate", "2026-07-15"),
    ]);
    match contact_eligibility(&e, &defaults()) {
        Eligibility::Eligible { method, .. } => assert_eq!(method, Method::Email),
        other => panic!("expected eligible email, got {other:?}"),
    }
}

#[test]
fn falls_back_to_use_sms_when_contact_method_absent() {
    let e = embedded(&[
        ("SurveysScheduled", "0"),
        ("NumDays", "1"),
        ("UseSMS", "1"),
        ("TimeSlots", "800"),
        ("StartDate", "2026-07-15"),
    ]);
    match contact_eligibility(&e, &defaults()) {
        Eligibility::Eligible { method, .. } => assert_eq!(method, Method::Sms),
        other => panic!("expected eligible sms, got {other:?}"),
    }
}

#[test]
fn falls_back_to_project_timezone_and_expiry() {
    let e = embedded(&[
        ("SurveysScheduled", "0"),
        ("NumDays", "1"),
        ("ContactMethod", "sms"),
        ("TimeSlots", "800"),
        ("StartDate", "2026-07-15"),
    ]);
    match contact_eligibility(&e, &defaults()) {
        Eligibility::Eligible {
            timezone,
            expire_minutes,
            ..
        } => {
            assert_eq!(timezone, DEFAULT_TIMEZONE);
            assert_eq!(expire_minutes, 60);
        }
        other => panic!("expected eligible, got {other:?}"),
    }
}

// The channel has to resolve for participants who are not eligible. Once a study is
// running every contact has a non-zero SurveysScheduled, and the Contacts table still
// needs to show whether each one is reached by SMS or email.
#[test]
fn delivery_method_resolves_for_ineligible_contacts() {
    let already_scheduled = embedded(&[
        ("SurveysScheduled", "68"),
        ("NumDays", "0"),
        ("ContactMethod", "email"),
    ]);
    assert!(matches!(
        contact_eligibility(&already_scheduled, &defaults()),
        Eligibility::Skipped(_)
    ));
    assert_eq!(delivery_method(&already_scheduled), Ok(Method::Email));
}

#[test]
fn delivery_method_matches_eligibility_resolution() {
    let cases = [
        (vec![("ContactMethod", "email")], Method::Email),
        (vec![("ContactMethod", "SMS")], Method::Sms),
        (vec![("UseSMS", "1")], Method::Sms),
        // ContactMethod wins over the legacy flag.
        (vec![("ContactMethod", "email"), ("UseSMS", "1")], Method::Email),
    ];
    for (fields, want) in cases {
        let mut e = embedded(&[
            ("SurveysScheduled", "0"),
            ("NumDays", "1"),
            ("TimeSlots", "800"),
            ("StartDate", "2026-07-15"),
        ]);
        for (k, v) in &fields {
            e.insert(k.to_string(), v.to_string());
        }
        assert_eq!(delivery_method(&e), Ok(want), "for {fields:?}");
        match contact_eligibility(&e, &defaults()) {
            Eligibility::Eligible { method, .. } => assert_eq!(method, want, "for {fields:?}"),
            other => panic!("expected eligible for {fields:?}, got {other:?}"),
        }
    }
}

#[test]
fn delivery_method_explains_when_undeterminable() {
    assert!(delivery_method(&embedded(&[])).unwrap_err().contains("UseSMS"));
    assert!(delivery_method(&embedded(&[("ContactMethod", "pigeon")]))
        .unwrap_err()
        .contains("not 'sms' or 'email'"));
}

#[test]
fn skip_reasons_are_specific() {
    let base = [
        ("SurveysScheduled", "0"),
        ("NumDays", "3"),
        ("ContactMethod", "sms"),
        ("TimeSlots", "800"),
        ("StartDate", "2026-07-15"),
    ];
    let with = |key: &str, val: &str| {
        let mut e = embedded(&base);
        e.insert(key.to_string(), val.to_string());
        e
    };
    let reason = |e: BTreeMap<String, String>| match contact_eligibility(&e, &defaults()) {
        Eligibility::Skipped(r) => r,
        other => panic!("expected skip, got {other:?}"),
    };

    assert!(reason(with("SurveysScheduled", "12")).contains("already scheduled"));
    assert!(reason(with("NumDays", "0")).contains("NumDays"));
    assert!(reason(with("TimeSlots", "")).contains("no time slots"));
    assert!(reason(with("TimeSlots", "2366")).contains("TimeSlots invalid"));
    assert!(reason(with("StartDate", "")).contains("StartDate"));
    assert!(reason(with("ContactMethod", "carrier-pigeon")).contains("not 'sms' or 'email'"));

    let mut no_method = embedded(&base);
    no_method.remove("ContactMethod");
    assert!(reason(no_method).contains("UseSMS"));
}

#[test]
fn bad_start_date_is_skipped_with_a_reason() {
    let slots = [Slot::Fixed(800)];
    let now = Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap();
    let (items, skipped) =
        build_contact_plan(&plan_inputs(&slots, "07/15/2026", 1), now, &mut rng());
    assert!(items.is_empty());
    assert!(skipped[0].reason.contains("YYYY-MM-DD"));
}

// --- message decoration ----------------------------------------------------

#[test]
fn message_suffix_is_unique_per_call() {
    let mut rng = rng();
    let a = decorate_message("Time for your survey", &mut rng);
    let b = decorate_message("Time for your survey", &mut rng);
    assert!(a.starts_with("Time for your survey"));
    assert_ne!(a, b, "duplicate bodies would trip Qualtrics' one-per-day rule");
}
