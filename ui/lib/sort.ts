export type SortDir = "asc" | "desc";

/** A comparable cell value. `null` means the row has nothing in this column. */
export type Cell = string | number | boolean | null;

function isBlank(v: Cell): boolean {
  return v === null || v === "" || (typeof v === "number" && Number.isNaN(v));
}

/**
 * Orders two cells, keeping blanks at the bottom whichever direction is active —
 * reversing the sort should reorder the real values, not bury them under empties.
 *
 * Text comparison is numeric-aware so "1745, 1800" lands near "800" the way a reader
 * expects rather than by character code.
 */
export function compareCells(a: Cell, b: Cell, dir: SortDir): number {
  if (isBlank(a) || isBlank(b)) {
    if (isBlank(a) && isBlank(b)) return 0;
    return isBlank(a) ? 1 : -1;
  }

  let result: number;
  if (typeof a === "number" && typeof b === "number") {
    result = a - b;
  } else if (typeof a === "boolean" && typeof b === "boolean") {
    result = a === b ? 0 : a ? -1 : 1;
  } else {
    result = String(a).localeCompare(String(b), undefined, {
      numeric: true,
      sensitivity: "base",
    });
  }
  return dir === "asc" ? result : -result;
}

/** Parses an embedded-data value that should sort as a number, not as text. */
export function asNumber(raw: string | undefined): number | null {
  if (raw === undefined || raw.trim() === "") return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

/** Trims to null so absent and whitespace-only values sort together. */
export function asText(raw: string | undefined): string | null {
  const t = (raw ?? "").trim();
  return t === "" ? null : t;
}

/** Advances sort state for a header click: same column flips, a new column starts ascending. */
export function nextSort(
  current: { key: string; dir: SortDir },
  key: string,
): { key: string; dir: SortDir } {
  if (current.key === key) {
    return { key, dir: current.dir === "asc" ? "desc" : "asc" };
  }
  return { key, dir: "asc" };
}
