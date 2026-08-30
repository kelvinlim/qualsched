import type { Account } from "./types";

/**
 * True when `account` is a usable Qualtrics login: it exists and
 * `dataCenter.trim()` is non-empty (the yu1 badge). A blank "+ Add account"
 * draft has `dataCenter: ""` and does not count.
 */
export function isUsableAccount(account: Account | null): boolean {
  return account !== null && account.dataCenter.trim() !== "";
}
