/**
 * Tiny runner for `isNewerVersion`. Invoked with
 * `node --experimental-strip-types lib/version.test.ts` so we do not add a
 * frontend test framework. Relative `.ts` import is for Node ESM.
 */
import { isNewerVersion } from "./version.ts";

const cases: Array<[latest: string, current: string, expected: boolean]> = [
  ["0.1.12", "0.2.0", false],
  ["0.2.0", "0.2.0", false],
  ["0.2.1", "0.2.0", true],
  ["v0.3.0", "0.2.0", true],
];

let failed = 0;
for (const [latest, current, expected] of cases) {
  const got = isNewerVersion(latest, current);
  if (got !== expected) {
    failed += 1;
    console.error(
      `isNewerVersion(${JSON.stringify(latest)}, ${JSON.stringify(current)}) === ${got}, expected ${expected}`,
    );
  }
}

if (failed > 0) {
  throw new Error(`${failed} of ${cases.length} version comparison checks failed`);
}

console.log(`version comparison: ${cases.length} checks passed`);
