/**
 * Dotted-numeric version comparison shared by the web GitHub-release check
 * (and kept in step with the desktop Rust `is_newer` helper).
 *
 * A segment that fails to parse makes the candidate "not newer" — a malformed
 * tag must never nag the user to upgrade. Leading `v` is ignored.
 */

function segments(version: string): number[] | null {
  const parts = version.trim().replace(/^v+/, "").split(".");
  const out: number[] = [];
  for (const part of parts) {
    if (!/^\d+$/.test(part)) return null;
    out.push(Number(part));
  }
  return out;
}

/** True only when `latest` is a strictly greater x.y.z than `current`. */
export function isNewerVersion(latest: string, current: string): boolean {
  const newer = segments(latest);
  const older = segments(current);
  if (!newer || !older) return false;

  const len = Math.max(newer.length, older.length);
  for (let i = 0; i < len; i++) {
    const a = newer[i] ?? 0;
    const b = older[i] ?? 0;
    if (a !== b) return a > b;
  }
  return false;
}
