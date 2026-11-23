/**
 * Heatmap labels, Monday-aligned weekly stacking, day detail popovers, active-only
 * filter, and the promise that this module does not touch browser storage.
 * Run with `node --experimental-strip-types`.
 */
import {
  WEEKDAY_HEADERS,
  currentWeekRange,
  dayDetail,
  dayGlyph,
  dayHasInvite,
  dayLabel,
  formatFullDate,
  formatShortDate,
  groupByWeeks,
  hasCurrentWeekInvite,
  heatOf,
  isoWeekday,
  lastSeven,
  monitorStatus,
  promptStatusLabel,
  rowSearchFields,
  rowWindow,
  statusPatchApplies,
  statusWriteIsCurrent,
  summaryText,
  visibleRows,
  windowSummary,
} from "./acquisition-view.ts";
import { matchesQuery } from "./filter.ts";
import type { AcquisitionDay, AcquisitionRow } from "./types.ts";

function assertEqual(got: unknown, expected: unknown, label: string) {
  const g = JSON.stringify(got);
  const e = JSON.stringify(expected);
  if (g !== e) throw new Error(`${label}: got ${g}, expected ${e}`);
}

const ratio = (date: string, completed: number, expected: number, later = 0): AcquisitionDay => ({
  date,
  kind: "ratio",
  completed,
  expected,
  later,
});

assertEqual(WEEKDAY_HEADERS.map((h) => h.short), ["M", "T", "W", "T", "F", "S", "S"], "Mon-Sun header");
assertEqual(WEEKDAY_HEADERS.map((h) => h.weekend), [false, false, false, false, false, true, true], "Sat/Sun marked weekend");

assertEqual(isoWeekday("2026-11-16"), 0, "2026-11-16 is Monday");
assertEqual(isoWeekday("2026-11-21"), 5, "2026-11-21 is Saturday");
assertEqual(isoWeekday("2026-11-22"), 6, "2026-11-22 is Sunday");
assertEqual(formatShortDate("2026-11-16"), "Nov 16", "short date");
assertEqual(formatShortDate("2026-01-05", true), "Jan 5, 2026", "short date with year");
assertEqual(formatFullDate("2026-11-18"), "Wed, Nov 18, 2026", "full date");

// Week grouping aligns every row Mon..Sun and omits blank gap weeks.
const weeks = groupByWeeks([
  ratio("2026-11-18", 2, 4), // Wed
  ratio("2026-11-21", 1, 4), // Sat
  ratio("2026-11-22", 0, 4), // Sun
  ratio("2026-11-23", 4, 4), // Next Mon
  ratio("2026-12-07", 3, 4), // Gap week omitted
]);
assertEqual(weeks.length, 3, "only weeks with days are emitted");
assertEqual(weeks[0].monday, "2026-11-16", "first week starts Monday");
assertEqual(weeks[0].label, "Nov 16", "same-year label omits year");
assertEqual(
  weeks[0].cells.map((c) => c?.date ?? null),
  [null, null, "2026-11-18", null, null, "2026-11-21", "2026-11-22"],
  "leading and mid-week null padding preserves Mon-Sun column alignment",
);
assertEqual(weeks[1].cells[0]?.date, "2026-11-23", "Monday sits in column 0");
assertEqual(weeks[2].monday, "2026-12-07", "gap week skipped cleanly");

// Multi-year span adds years to week labels.
const crossYear = groupByWeeks([
  ratio("2025-12-30", 1, 2),
  ratio("2026-01-05", 2, 2),
]);
assertEqual(crossYear.map((w) => w.label), ["Dec 29, 2025", "Jan 5, 2026"], "multi-year week labels include year");

// Rolling 7-day window ending Sunday fits 1 row; ending Wednesday stacks across 2 rows.
const sevenMidWeek = groupByWeeks(lastSeven([], "2026-11-18"));
assertEqual(sevenMidWeek.length, 2, "rolling 7-day window splits across Mon-Sun rows");
assertEqual(
  sevenMidWeek[0].cells.map((c) => c?.date ?? null),
  [null, null, null, "2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15"],
  "prior Thu-Sun aligned to columns 3..6",
);
assertEqual(
  sevenMidWeek[1].cells.map((c) => c?.date ?? null),
  ["2026-11-16", "2026-11-17", "2026-11-18", null, null, null, null],
  "current Mon-Wed aligned to columns 0..2",
);

// Study window strips unrelated nonStudy tail days when active study days exist.
const rowSample: AcquisitionRow = {
  contactId: "CID_1",
  displayName: "P1",
  monitor: "active",
  timezone: "America/Chicago",
  timezoneSource: "contact",
  today: "2026-11-22",
  definitive: true,
  ambiguous: 0,
  unmatchedCompletions: 0,
  duplicateCompletions: 0,
  days: [
    ratio("2026-10-01", 4, 4),
    { date: "2026-11-22", kind: "nonStudy", later: 0 },
  ],
  toDate: { completed: 4, expected: 4, provisional: false },
};
assertEqual(
  rowWindow(rowSample, "study").map((d) => d.date),
  ["2026-10-01"],
  "study window omits unrelated nonStudy tail days",
);
assertEqual(rowWindow(rowSample, "7").length, 7, "7-day window keeps 7 days");

// Prompt detail and hover info.
assertEqual(promptStatusLabel("finished"), "Completed");
assertEqual(promptStatusLabel("started"), "Started (not finished)");
assertEqual(promptStatusLabel("sent"), "Sent (no response)");
assertEqual(promptStatusLabel("failed"), "Delivery failed");
assertEqual(promptStatusLabel("scheduled"), "Scheduled (not yet due)");
assertEqual(promptStatusLabel("unknown"), "Status unknown");

const richDay: AcquisitionDay = {
  date: "2026-11-21",
  kind: "ratio",
  completed: 3,
  expected: 4,
  later: 1,
  prompts: [{ sendLocal: "08:00", method: "sms", status: "finished" }],
};
const detail = dayDetail(richDay);
assertEqual(detail.heading, "Sat, Nov 21, 2026", "detail heading");
assertEqual(detail.isWeekend, true, "Saturday flagged as weekend");
assertEqual(detail.summary, "3 of 4 completed (75%)", "detail summary");
assertEqual(detail.laterNote, "1 scheduled later today (not due yet)", "detail later note");
assertEqual(detail.prompts.length, 1, "detail prompts carried through");

assertEqual(heatOf(ratio("2026-07-15", 0, 4)), "0", "true zero is not an empty day");
assertEqual(heatOf(ratio("2026-07-15", 1, 4)), "1", "1/4");
assertEqual(heatOf(ratio("2026-07-15", 2, 4)), "2", "2/4");
assertEqual(heatOf(ratio("2026-07-15", 3, 4)), "3", "3/4");
assertEqual(heatOf(ratio("2026-07-15", 4, 4)), "4", "4/4");
assertEqual(heatOf({ date: "2026-07-16", kind: "future", later: 2 }), "future", "future");
assertEqual(heatOf({ date: "2026-07-12", kind: "none", later: 0 }), "none", "no expected");
assertEqual(
  heatOf({ date: "2026-07-01", kind: "nonStudy", later: 0 }),
  "nonStudy",
  "outside study",
);
assertEqual(heatOf({ date: "2026-07-15", kind: "unknown", later: 0 }), "unknown", "unknown");

assertEqual(
  dayLabel(ratio("2026-07-15", 1, 2, 2)),
  "2026-07-15: 1 of 2 completed; 2 later the same day not counted yet",
  "current day counts only prompts already due",
);
assertEqual(
  dayLabel(ratio("2026-07-14", 0, 4)),
  "2026-07-14: 0 of 4 completed",
  "zero completed still names the denominator",
);
assertEqual(
  dayLabel({ date: "2026-07-16", kind: "future", later: 4 }),
  "2026-07-16: 4 scheduled, none due yet",
  "future is not 0/4",
);
assertEqual(
  dayLabel({ date: "2026-07-17", kind: "none", later: 0 }),
  "2026-07-17: no surveys expected",
  "none",
);
assertEqual(
  dayLabel({ date: "2026-07-10", kind: "nonStudy", later: 0 }),
  "2026-07-10: outside the study",
  "non-study",
);
assertEqual(
  dayLabel({ date: "2026-07-15", kind: "unknown", later: 0 }),
  "2026-07-15: expected count unknown",
  "unknown denominator",
);
assertEqual(dayGlyph(ratio("2026-07-14", 0, 4)), "0", "zero glyph");
assertEqual(dayGlyph({ date: "2026-07-16", kind: "future", later: 1 }), "·", "future glyph");
assertEqual(dayGlyph({ date: "2026-07-15", kind: "unknown", later: 0 }), "?", "unknown glyph");

assertEqual(summaryText(6, 7, false), "6/7", "final count");
assertEqual(summaryText(6, 7, true), "at least 6/7", "provisional count");
assertEqual(summaryText(null, null, true), "expected unknown", "unknown total");

const days = lastSeven(
  [ratio("2026-07-15", 1, 1), { date: "2026-07-09", kind: "nonStudy", later: 0 }],
  "2026-07-15",
);
assertEqual(
  days.map((day) => day.date),
  [
    "2026-07-09",
    "2026-07-10",
    "2026-07-11",
    "2026-07-12",
    "2026-07-13",
    "2026-07-14",
    "2026-07-15",
  ],
  "last 7 local dates",
);
assertEqual(days[1].kind, "unknown", "a missing day in the window is unknown, not zero");
assertEqual(windowSummary(days).expected, null, "unknown day blocks a confident window total");
assertEqual(
  windowSummary([
    ratio("2026-07-13", 2, 2),
    ratio("2026-07-14", 0, 1),
    { date: "2026-07-16", kind: "future", later: 3 },
  ]),
  { completed: 2, expected: 3 },
  "future prompts are outside the window total",
);

assertEqual(
  currentWeekRange("2026-11-22"),
  { start: "2026-11-16", end: "2026-11-22" },
  "Sunday belongs to the Monday-Sunday week starting Nov 16",
);
assertEqual(
  currentWeekRange("2026-11-18"),
  { start: "2026-11-16", end: "2026-11-22" },
  "Wednesday belongs to the same Monday-Sunday week",
);
assertEqual(dayHasInvite(ratio("2026-11-18", 0, 1)), true, "ratio day counts as having invites");
assertEqual(dayHasInvite({ date: "2026-11-20", kind: "future", later: 2 }), true, "future day counts as having invites");
assertEqual(dayHasInvite({ date: "2026-11-18", kind: "none", later: 0 }), false, "none day has no invites");
assertEqual(dayHasInvite({ date: "2026-11-18", kind: "nonStudy", later: 0 }), false, "nonStudy day has no invites");

const activeCurrentRatio = {
  monitor: "active",
  name: "Ada Lovelace",
  today: "2026-11-22",
  days: [
    { date: "2026-11-10", kind: "ratio" as const, completed: 1, expected: 1, later: 0 },
    { date: "2026-11-18", kind: "ratio" as const, completed: 0, expected: 1, later: 0 },
  ],
};
const activeCurrentFuture = {
  monitor: "active",
  name: "Alan Turing",
  today: "2026-11-22",
  days: [{ date: "2026-11-22", kind: "future" as const, later: 2 }],
};
const activePriorWeekOnly = {
  monitor: "active",
  name: "Katherine Johnson",
  today: "2026-11-22",
  days: [
    { date: "2026-11-15", kind: "ratio" as const, completed: 4, expected: 4, later: 0 },
    { date: "2026-11-18", kind: "none" as const, later: 0 },
    { date: "2026-11-22", kind: "nonStudy" as const, later: 0 },
  ],
};
const inactiveCurrentWeek = {
  monitor: "inactive",
  name: "Grace Hopper",
  today: "2026-11-22",
  days: [{ date: "2026-11-18", kind: "ratio" as const, completed: 2, expected: 2, later: 0 }],
};
const rows = [
  activeCurrentRatio,
  activeCurrentFuture,
  activePriorWeekOnly,
  inactiveCurrentWeek,
];
assertEqual(hasCurrentWeekInvite(activeCurrentRatio), true, "ratio in current week matches");
assertEqual(hasCurrentWeekInvite(activeCurrentFuture), true, "future invite in current week matches");
assertEqual(hasCurrentWeekInvite(activePriorWeekOnly), false, "prior-week invite does not match current week");
assertEqual(
  visibleRows(rows, true).map((row) => row.name),
  ["Ada Lovelace", "Alan Turing"],
  "active only keeps non-inactive rows with current-week survey invitations",
);
assertEqual(visibleRows(rows, false).length, 4, "showing all returns every row regardless of status or week");
assertEqual(rows.length, 4, "filter does not mutate the report");
assertEqual(monitorStatus(undefined), "active", "missing flag stays active");
assertEqual(monitorStatus("inactive"), "inactive", "explicit inactive");
assertEqual(monitorStatus("ACTIVE"), "active", "only the word inactive hides a row");
assertEqual(
  statusPatchApplies("acct", "proj", "acct", "proj", true),
  true,
  "status write applies on the same account and profile",
);
assertEqual(
  statusPatchApplies("acct", "other", "acct", "proj", true),
  false,
  "status write does not patch a different profile",
);
assertEqual(
  statusPatchApplies("acct", "proj", "acct", "proj", false),
  false,
  "status write does not patch after the report was cleared",
);
assertEqual(statusWriteIsCurrent(1, 1, 3, 3), true, "this row's own write is still current");
assertEqual(
  statusWriteIsCurrent(1, 1, 3, 4),
  false,
  "a newer click on the same participant replaces the earlier write",
);
assertEqual(
  statusWriteIsCurrent(1, 2, 3, 3),
  false,
  "switching profile cancels an in-flight status write",
);
assertEqual(
  statusWriteIsCurrent(1, 2, 1, 1),
  false,
  "a stale save must not release a new save that was given the same ticket number",
);

// Search filter by name, reference, phone (digits normalized), and email, respecting Hide PHI.
const searchableRow = {
  contactId: "CID_42",
  displayName: "Ada Lovelace",
  extRef: "R34805",
  phone: "(612) 555-1234",
  email: "ada@example.com",
};
assertEqual(matchesQuery("ada", rowSearchFields(searchableRow, false)), true, "search by name");
assertEqual(matchesQuery("R34805", rowSearchFields(searchableRow, false)), true, "search by extRef");
assertEqual(matchesQuery("6125551234", rowSearchFields(searchableRow, false)), true, "search by digits-only phone");
assertEqual(matchesQuery("example.com", rowSearchFields(searchableRow, false)), true, "search by email");
assertEqual(matchesQuery("ada 1234", rowSearchFields(searchableRow, false)), true, "search multi-term AND");
assertEqual(matchesQuery("grace", rowSearchFields(searchableRow, false)), false, "search misses non-matching text");
assertEqual(matchesQuery("R34805", rowSearchFields(searchableRow, true)), true, "hidePhi still searches extRef");
assertEqual(matchesQuery("CID_42", rowSearchFields(searchableRow, true)), true, "hidePhi still searches contactId");
assertEqual(matchesQuery("Ada", rowSearchFields(searchableRow, true)), false, "hidePhi excludes name from search");
assertEqual(matchesQuery("6125551234", rowSearchFields(searchableRow, true)), false, "hidePhi excludes phone from search");
assertEqual(matchesQuery("example.com", rowSearchFields(searchableRow, true)), false, "hidePhi excludes email from search");

const source = await import("node:fs/promises").then((fs) =>
  fs.readFile(new URL("./acquisition-view.ts", import.meta.url), "utf8"),
);
for (const forbidden of ["localStorage", "sessionStorage", "indexedDB", "writeFile"]) {
  if (source.includes(forbidden)) {
    throw new Error(`acquisition view mentions ${forbidden}`);
  }
}

console.log("acquisition-view tests ok");
