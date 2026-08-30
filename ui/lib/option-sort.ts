/** An item in a Load from Qualtrics picker. `name` is the Qualtrics name or description. */
export interface SortableOption {
  id: string;
  label?: string;
  name?: string;
}

const UNNAMED = "(unnamed)";

/**
 * The Qualtrics name used for ordering. Falls back to `label` only when `name` is
 * omitted, so a future picker that forgets `name` still sorts roughly by what is
 * shown. Empty, whitespace-only, and "(unnamed)" are treated as unnamed.
 */
function sortName(item: SortableOption): string | null {
  const raw = item.name !== undefined ? item.name : (item.label ?? "");
  const trimmed = raw.trim();
  if (
    trimmed === "" ||
    trimmed.localeCompare(UNNAMED, undefined, { sensitivity: "base" }) === 0
  ) {
    return null;
  }
  return trimmed;
}

/** Case-insensitive, locale-aware compare. Unnamed items sort after named ones, then by id. */
export function compareQualtricsOptions(a: SortableOption, b: SortableOption): number {
  const aName = sortName(a);
  const bName = sortName(b);
  if (aName === null || bName === null) {
    if (aName === null && bName === null) {
      return a.id.localeCompare(b.id, undefined, { sensitivity: "base" });
    }
    return aName === null ? 1 : -1;
  }
  const byName = aName.localeCompare(bName, undefined, { sensitivity: "base" });
  if (byName !== 0) return byName;
  return a.id.localeCompare(b.id, undefined, { sensitivity: "base" });
}

/** Returns a new array ordered by Qualtrics name. Does not mutate `options`. */
export function sortQualtricsOptions<T extends SortableOption>(options: T[]): T[] {
  return [...options].sort(compareQualtricsOptions);
}
