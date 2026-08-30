import type { ScreenName } from "./state.svelte";

/**
 * Sidebar items and the account/project gates shared by the desktop and web
 * shells. Disabled/title copy lives here so the two App.svelte files cannot drift.
 *
 * `hint` is the hover text. When an item is greyed out the title also says what
 * is missing — otherwise a disabled button explains nothing.
 */
export type NavItem = {
  screen: ScreenName;
  label: string;
  needsAccount: boolean;
  needsProject: boolean;
  hint: string;
};

export const NAV_ITEMS: NavItem[] = [
  {
    screen: "accounts",
    label: "Accounts",
    needsAccount: false,
    needsProject: false,
    hint: "One per Qualtrics login: API token, data center, contact directory, message library",
  },
  {
    screen: "project",
    label: "Survey profile",
    needsAccount: true,
    needsProject: false,
    hint: "One per study: survey, mailing list, message templates, default schedule",
  },
  {
    screen: "contacts",
    label: "Contacts",
    needsAccount: false,
    needsProject: true,
    hint: "Your participants and each one's schedule",
  },
  {
    screen: "schedule",
    label: "Schedule",
    needsAccount: false,
    needsProject: true,
    hint: "Work out the invitations, review them, then send",
  },
  {
    screen: "distributions",
    label: "Distributions",
    needsAccount: false,
    needsProject: true,
    hint: "Invitations already booked with Qualtrics, and cancelling them",
  },
  {
    screen: "import",
    label: "Import Config",
    needsAccount: true,
    needsProject: false,
    hint: "Read a settings file from the old command-line tool, or one exported here",
  },
  {
    screen: "export",
    label: "Export Config",
    needsAccount: false,
    needsProject: true,
    hint: "Save this survey profile as a file another computer can import",
  },
  {
    screen: "guide",
    label: "User guide",
    needsAccount: false,
    needsProject: false,
    hint: "The full guide to setting up and running a study",
  },
];

export function navItemDisabled(
  item: Pick<NavItem, "needsAccount" | "needsProject">,
  hasAccount: boolean,
  hasProject: boolean,
): boolean {
  if (item.needsProject && !hasProject) return true;
  if (item.needsAccount && !hasAccount) return true;
  return false;
}

export function navItemTitle(
  item: Pick<NavItem, "needsAccount" | "needsProject" | "hint">,
  hasAccount: boolean,
  hasProject: boolean,
): string {
  if (item.needsProject && !hasProject) {
    return `${item.hint} — choose an account and a survey profile first`;
  }
  if (item.needsAccount && !hasAccount) {
    return `${item.hint} — choose an account first`;
  }
  return item.hint;
}
