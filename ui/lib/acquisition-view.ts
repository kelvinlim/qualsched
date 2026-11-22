/**
 * Display rules for the acquisition heatmap. Pure: no browser storage and no
 * network. The screen holds the report in component state and drops it when
 * the account, profile, or screen changes.
 */
import type { AcquisitionDay, AcquisitionRow } from "./types";

export type Heat =
  | "0"
  | "1"
  | "2"
  | "3"
  | "4"
  | "future"
  | "none"
  | "nonStudy"
  | "unknown";

/**
 * Two rows can be saved at once. A write is current when the screen is still the
 * one it started on, and no newer write for this same participant has started.
 * Another participant's write does not cancel it.
 */
export function statusWriteIsCurrent(
  startedContext: number,
  currentContext: number,
  startedTicket: number,
  currentTicket: number,
): boolean {
  return startedContext === currentContext && startedTicket === currentTicket;
}

/** A status write may return after the researcher has switched account or profile. */
export function statusPatchApplies(
  currentAccountId: string | null,
  currentProjectId: string | null,
  startedAccountId: string,
  startedProjectId: string,
  reportPresent: boolean,
): boolean {
  return (
    reportPresent &&
    currentAccountId === startedAccountId &&
    currentProjectId === startedProjectId
  );
}

export function monitorStatus(raw: string | null | undefined): "active" | "inactive" {
  return (raw ?? "").trim().toLowerCase() === "inactive" ? "inactive" : "active";
}

export function visibleRows<T extends { monitor: string }>(rows: T[], activeOnly: boolean): T[] {
  if (!activeOnly) return rows;
  return rows.filter((row) => row.monitor !== "inactive");
}

function shiftDate(iso: string, days: number): string {
  const [year, month, day] = iso.split("-").map(Number);
  const utc = new Date(Date.UTC(year, (month || 1) - 1, day || 1));
  utc.setUTCDate(utc.getUTCDate() + days);
  return utc.toISOString().slice(0, 10);
}

/** The participant's last 7 local dates, ending on `today`. Missing days are unknown. */
export function lastSeven(days: AcquisitionDay[], today: string): AcquisitionDay[] {
  const byDate = new Map(days.map((day) => [day.date, day]));
  const out: AcquisitionDay[] = [];
  for (let offset = -6; offset <= 0; offset += 1) {
    const date = shiftDate(today, offset);
    out.push(byDate.get(date) ?? { date, kind: "unknown", later: 0 });
  }
  return out;
}

export function heatOf(day: AcquisitionDay): Heat {
  if (day.kind !== "ratio") return day.kind;
  const expected = day.expected ?? 0;
  const completed = day.completed ?? 0;
  if (expected <= 0 || completed <= 0) return "0";
  const fraction = completed / expected;
  if (fraction < 0.34) return "1";
  if (fraction < 0.67) return "2";
  if (fraction < 1) return "3";
  return "4";
}

/** Accessible name. Color is not the only signal; this text is the label. */
export function dayLabel(day: AcquisitionDay): string {
  if (day.kind === "ratio") {
    const completed = day.completed ?? 0;
    const expected = day.expected ?? 0;
    const later =
      day.later > 0 ? `; ${day.later} later the same day not counted yet` : "";
    return `${day.date}: ${completed} of ${expected} completed${later}`;
  }
  if (day.kind === "future") {
    const count = day.later === 1 ? "1 scheduled" : `${day.later} scheduled`;
    return `${day.date}: ${count}, none due yet`;
  }
  if (day.kind === "none") return `${day.date}: no surveys expected`;
  if (day.kind === "nonStudy") return `${day.date}: outside the study`;
  return `${day.date}: expected count unknown`;
}

export function summaryText(
  completed: number | null | undefined,
  expected: number | null | undefined,
  provisional: boolean,
): string {
  if (completed == null || expected == null) return "expected unknown";
  return `${provisional ? "at least " : ""}${completed}/${expected}`;
}

/** Sum of due prompts in the days on screen. Unknown days make the total unknown. */
export function windowSummary(days: AcquisitionDay[]): {
  completed: number | null;
  expected: number | null;
} {
  if (days.some((day) => day.kind === "unknown")) {
    return { completed: null, expected: null };
  }
  let completed = 0;
  let expected = 0;
  for (const day of days) {
    if (day.kind !== "ratio") continue;
    completed += day.completed ?? 0;
    expected += day.expected ?? 0;
  }
  return { completed, expected };
}

export function rowWindow(row: AcquisitionRow, span: "7" | "study"): AcquisitionDay[] {
  return span === "7" ? lastSeven(row.days, row.today) : row.days;
}

/** Glyph inside the block so the state is readable without color. */
export function dayGlyph(day: AcquisitionDay): string {
  if (day.kind === "ratio") return String(day.completed ?? 0);
  if (day.kind === "future") return "·";
  if (day.kind === "none") return "–";
  if (day.kind === "nonStudy") return "";
  return "?";
}
