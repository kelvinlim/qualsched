/**
 * Tiny runner for sidebar account/project gates. Invoked with
 * `node --experimental-strip-types lib/nav.test.ts` so we do not add a
 * frontend test framework. Relative `.ts` import is for Node ESM.
 *
 * `hasAccount` here is the usable-login flag (non-empty data center), not
 * "any selected account". A blank "+ Add account" draft is `hasAccount: false`.
 */
import { isUsableAccount } from "./account.ts";
import { NAV_ITEMS, navItemDisabled, navItemTitle } from "./nav.ts";
import type { Account } from "./types.ts";

function item(screen: string) {
  const found = NAV_ITEMS.find((n) => n.screen === screen);
  if (!found) throw new Error(`missing nav item ${screen}`);
  return found;
}

function assertEqual(got: unknown, expected: unknown, label: string) {
  const g = JSON.stringify(got);
  const e = JSON.stringify(expected);
  if (g !== e) {
    throw new Error(`${label}: got ${g}, expected ${e}`);
  }
}

const none = { hasAccount: false, hasProject: false };
const accountOnly = { hasAccount: true, hasProject: false };
const both = { hasAccount: true, hasProject: true };

const cases: Array<{
  screen: string;
  gate: typeof none;
  disabled: boolean;
  titleSuffix?: string;
}> = [
  { screen: "accounts", gate: none, disabled: false },
  { screen: "guide", gate: none, disabled: false },
  { screen: "project", gate: none, disabled: true, titleSuffix: " — choose an account first" },
  { screen: "import", gate: none, disabled: true, titleSuffix: " — choose an account first" },
  { screen: "project", gate: accountOnly, disabled: false },
  { screen: "import", gate: accountOnly, disabled: false },
  { screen: "contacts", gate: accountOnly, disabled: true, titleSuffix: " — choose an account and a survey profile first" },
  { screen: "schedule", gate: accountOnly, disabled: true, titleSuffix: " — choose an account and a survey profile first" },
  { screen: "distributions", gate: accountOnly, disabled: true, titleSuffix: " — choose an account and a survey profile first" },
  { screen: "export", gate: accountOnly, disabled: true, titleSuffix: " — choose an account and a survey profile first" },
  { screen: "contacts", gate: both, disabled: false },
  { screen: "export", gate: both, disabled: false },
  { screen: "project", gate: both, disabled: false },
  { screen: "import", gate: both, disabled: false },
];

for (const { screen, gate, disabled, titleSuffix } of cases) {
  const nav = item(screen);
  assertEqual(
    navItemDisabled(nav, gate.hasAccount, gate.hasProject),
    disabled,
    `${screen} disabled (account=${gate.hasAccount}, project=${gate.hasProject})`,
  );
  const title = navItemTitle(nav, gate.hasAccount, gate.hasProject);
  if (titleSuffix) {
    assertEqual(title, `${nav.hint}${titleSuffix}`, `${screen} disabled title`);
  } else {
    assertEqual(title, nav.hint, `${screen} enabled title is the hint`);
  }
}

assertEqual(
  NAV_ITEMS.filter((n) => n.needsAccount).map((n) => n.screen),
  ["project", "import"],
  "only survey profile and import wait on an account",
);
assertEqual(
  NAV_ITEMS.filter((n) => n.needsProject).map((n) => n.screen),
  ["contacts", "schedule", "distributions", "export"],
  "contacts/schedule/distributions/export still wait on a survey profile",
);

function account(dataCenter: string): Account {
  return {
    id: "a1",
    name: "New account",
    dataCenter,
    verifyTls: true,
    defaultDirectory: "",
    libraryId: "",
    projects: [],
  };
}

assertEqual(isUsableAccount(null), false, "no selection is not usable");
assertEqual(isUsableAccount(account("")), false, "blank draft (empty dataCenter) is not usable");
assertEqual(isUsableAccount(account("   ")), false, "whitespace-only dataCenter is not usable");
assertEqual(isUsableAccount(account("yu1")), true, "saved data center is usable");

const blankDraft = { hasAccount: isUsableAccount(account("")), hasProject: false };
assertEqual(
  navItemDisabled(item("project"), blankDraft.hasAccount, blankDraft.hasProject),
  true,
  "Survey profile disabled for a blank draft",
);
assertEqual(
  navItemDisabled(item("import"), blankDraft.hasAccount, blankDraft.hasProject),
  true,
  "Import Config disabled for a blank draft",
);

console.log(`nav gates: ${cases.length + 8} checks passed`);
