/**
 * Tiny runner for `sortQualtricsOptions`. Invoked with
 * `node --experimental-strip-types lib/option-sort.test.ts` so we do not add a
 * frontend test framework. Relative `.ts` import is for Node ESM.
 */
import { sortQualtricsOptions, type SortableOption } from "./option-sort.ts";

function ids(items: SortableOption[]): string[] {
  return items.map((item) => item.id);
}

function assertEqual(got: unknown, expected: unknown, label: string) {
  const g = JSON.stringify(got);
  const e = JSON.stringify(expected);
  if (g !== e) {
    throw new Error(`${label}: got ${g}, expected ${e}`);
  }
}

assertEqual(
  ids(
    sortQualtricsOptions([
      { id: "2", name: "(unnamed)" },
      { id: "1", name: "Beta" },
      { id: "3", name: "alpha" },
    ]),
  ),
  ["3", "1", "2"],
  "named before unnamed, case-insensitive",
);

assertEqual(
  ids(
    sortQualtricsOptions([
      { id: "empty", name: "" },
      { id: "missing", name: undefined },
      { id: "ws", name: "   " },
      { id: "named", name: "Zed" },
      { id: "UNNAMED", name: "(Unnamed)" },
    ]),
  ),
  ["named", "empty", "missing", "UNNAMED", "ws"],
  "empty, missing, and (unnamed) sort after named, then by id",
);

assertEqual(
  ids(
    sortQualtricsOptions([
      { id: "b", name: "Same" },
      { id: "a", name: "Same" },
    ]),
  ),
  ["a", "b"],
  "equal names tie-break by id",
);

assertEqual(
  ids(
    sortQualtricsOptions([
      { id: "sv2", label: "Zebra (SV_2)", name: "Apple" },
      { id: "sv1", label: "Apple (SV_1)", name: "Zebra" },
    ]),
  ),
  ["sv2", "sv1"],
  "sorts by name, not the full option label",
);

assertEqual(
  ids(
    sortQualtricsOptions([
      { id: "2", label: "beta (2)" },
      { id: "1", label: "Alpha (1)" },
    ]),
  ),
  ["1", "2"],
  "falls back to label when name is omitted",
);

console.log("option-sort: 5 checks passed");
