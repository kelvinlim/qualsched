/**
 * Heatmap labels, the active-only filter, and the promise that this module
 * does not touch browser storage. Run with `node --experimental-strip-types`.
 */
import {
  dayGlyph,
  dayLabel,
  heatOf,
  lastSeven,
  monitorStatus,
  statusPatchApplies,
  statusWriteIsCurrent,
  summaryText,
  visibleRows,
  windowSummary,
} from "./acquisition-view.ts";
import type { AcquisitionDay } from "./types.ts";

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
  windowSummary([ratio("2026-07-13", 2, 2), ratio("2026-07-14", 0, 1), { date: "2026-07-16", kind: "future", later: 3 }]),
  { completed: 2, expected: 3 },
  "future prompts are outside the window total",
);

const rows = [
  { monitor: "active", name: "Ada Lovelace" },
  { monitor: "inactive", name: "Grace Hopper" },
];
assertEqual(
  visibleRows(rows, true).map((row) => row.name),
  ["Ada Lovelace"],
  "active only hides inactive and does not delete them from the source list",
);
assertEqual(visibleRows(rows, false).length, 2, "showing inactive is a display choice");
assertEqual(rows.length, 2, "filter does not mutate the report");
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

const source = await import("node:fs/promises").then((fs) =>
  fs.readFile(new URL("./acquisition-view.ts", import.meta.url), "utf8"),
);
for (const forbidden of ["localStorage", "sessionStorage", "indexedDB", "writeFile"]) {
  if (source.includes(forbidden)) {
    throw new Error(`acquisition view mentions ${forbidden}`);
  }
}

console.log("acquisition-view tests ok");
