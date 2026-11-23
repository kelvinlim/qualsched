/**
 * Display rules for the acquisition heatmap. Pure: no browser storage and no
 * network. The screen holds the report in component state and drops it when
 * the account, profile, or screen changes.
 */
import type {
  AcquisitionDay,
  AcquisitionPrompt,
  AcquisitionPromptStatus,
  AcquisitionRow,
} from "./types";

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

export const WEEKDAY_HEADERS = [
  { short: "M", full: "Monday", weekend: false },
  { short: "T", full: "Tuesday", weekend: false },
  { short: "W", full: "Wednesday", weekend: false },
  { short: "T", full: "Thursday", weekend: false },
  { short: "F", full: "Friday", weekend: false },
  { short: "S", full: "Saturday", weekend: true },
  { short: "S", full: "Sunday", weekend: true },
] as const;

const MONTHS_SHORT = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

const WEEKDAYS_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

export interface AcquisitionWeek {
  monday: string;
  label: string;
  cells: (AcquisitionDay | null)[];
}

export interface AcquisitionDayDetail {
  heading: string;
  isWeekend: boolean;
  summary: string;
  laterNote: string;
  prompts: AcquisitionPrompt[];
}

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

/** ISO day of week for YYYY-MM-DD: 0 = Monday ... 6 = Sunday. */
export function isoWeekday(isoDate: string): number {
  const [year, month, day] = isoDate.split("-").map(Number);
  const utc = new Date(Date.UTC(year, (month || 1) - 1, day || 1));
  return (utc.getUTCDay() + 6) % 7;
}

export function formatShortDate(isoDate: string, includeYear = false): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  const mon = MONTHS_SHORT[(month || 1) - 1] ?? "Jan";
  const d = Number(day) || 1;
  return includeYear ? `${mon} ${d}, ${year}` : `${mon} ${d}`;
}

export function formatFullDate(isoDate: string): string {
  const dow = WEEKDAYS_SHORT[isoWeekday(isoDate)] ?? "Mon";
  return `${dow}, ${formatShortDate(isoDate, true)}`;
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

/**
 * Group ordered days into Monday–Sunday rows so identical weekdays align
 * vertically across weeks. Non-present gap weeks are omitted rather than
 * generating blank weeks.
 */
export function groupByWeeks(days: AcquisitionDay[]): AcquisitionWeek[] {
  if (days.length === 0) return [];
  const buckets = new Map<string, (AcquisitionDay | null)[]>();
  const order: string[] = [];
  for (const day of days) {
    const col = isoWeekday(day.date);
    const monday = shiftDate(day.date, -col);
    let cells = buckets.get(monday);
    if (!cells) {
      cells = [null, null, null, null, null, null, null];
      buckets.set(monday, cells);
      order.push(monday);
    }
    cells[col] = day;
  }
  const years = new Set(order.map((monday) => monday.slice(0, 4)));
  const multiYear = years.size > 1;
  return order.map((monday) => ({
    monday,
    label: formatShortDate(monday, multiYear),
    cells: buckets.get(monday)!,
  }));
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

export function promptStatusLabel(status: AcquisitionPromptStatus): string {
  switch (status) {
    case "finished":
      return "Completed";
    case "started":
      return "Started (not finished)";
    case "sent":
      return "Sent (no response)";
    case "failed":
      return "Delivery failed";
    case "scheduled":
      return "Scheduled (not yet due)";
    default:
      return "Status unknown";
  }
}

export function dayDetail(day: AcquisitionDay): AcquisitionDayDetail {
  const heading = formatFullDate(day.date);
  const isWeekend = isoWeekday(day.date) >= 5;
  const prompts = day.prompts ?? [];
  let summary = "";
  let laterNote = "";
  if (day.kind === "ratio") {
    const completed = day.completed ?? 0;
    const expected = day.expected ?? 0;
    if (expected > 0) {
      const pct = Math.round((completed / expected) * 100);
      summary = `${completed} of ${expected} completed (${pct}%)`;
    } else {
      summary = `${completed} of ${expected} completed`;
    }
    if (day.later > 0) {
      laterNote = `${day.later} scheduled later today (not due yet)`;
    }
  } else if (day.kind === "future") {
    const count = day.later === 1 ? "1 scheduled" : `${day.later} scheduled`;
    summary = `${count}, none due yet`;
  } else if (day.kind === "none") {
    summary = "No surveys expected";
  } else if (day.kind === "nonStudy") {
    summary = "Outside the study window";
  } else {
    summary = "Completion status unknown";
  }
  return { heading, isWeekend, summary, laterNote, prompts };
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
  if (span === "7") return lastSeven(row.days, row.today);
  return row.days.some((day) => day.kind !== "nonStudy")
    ? row.days.filter((day) => day.kind !== "nonStudy")
    : row.days;
}

/** Glyph inside the block so the state is readable without color. */
export function dayGlyph(day: AcquisitionDay): string {
  if (day.kind === "ratio") return String(day.completed ?? 0);
  if (day.kind === "future") return "·";
  if (day.kind === "none") return "–";
  if (day.kind === "nonStudy") return "";
  return "?";
}
