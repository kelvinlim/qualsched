/**
 * Row filtering for the participant tables. Kept apart from `sort.ts`, which is about
 * ordering one column's `Cell` values and shares no types with this.
 *
 * There is no frontend test runner in this project; if one is ever added, `matchesQuery`
 * is the first thing worth covering — the digit handling below has the edge cases.
 */

/** Digits only, so "(612) 555-1234" and "6125551234" compare equal. */
function digits(value: string): string {
  return value.replace(/\D+/g, "");
}

/**
 * True when every word of `query` matches at least one of `fields`.
 *
 * Words are ANDed, so "kelvin 612" narrows by name and number together. Each word is
 * tried twice: as plain text, and — when it contains digits — against each field with its
 * punctuation stripped. Qualtrics stores phone numbers as free text, so what is stored and
 * what someone types almost never agree character for character.
 *
 * Digits are normalized per field rather than over the joined row: joining first would let
 * a query match a run of digits spanning two fields that exists nowhere in the data.
 */
export function matchesQuery(
  query: string,
  fields: (string | null | undefined)[],
): boolean {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return true;

  const texts = fields.filter((f): f is string => !!f).map((f) => f.toLowerCase());
  const numbers = texts.map(digits).filter((d) => d.length > 0);

  return terms.every((term) => {
    if (texts.some((text) => text.includes(term))) return true;
    const wanted = digits(term);
    return wanted.length > 0 && numbers.some((n) => n.includes(wanted));
  });
}
