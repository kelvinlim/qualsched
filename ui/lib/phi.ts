/**
 * Presentation helpers for the "Hide PHI" toggle.
 *
 * When Hide PHI is enabled, participant names fall back to external reference
 * (`extRef`) when present, otherwise Qualtrics contact ID, and direct contact
 * fields (phone, email, destination) are masked. Nothing here writes participant
 * data to storage — only the boolean toggle preference is persisted.
 */

export const HIDE_PHI_KEY = "qualsched.hidePhi";
export const PHI_MASK = "••••";

export type PhiStorage = {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
};

export function readHidePhi(storage?: Pick<PhiStorage, "getItem"> | null): boolean {
  if (!storage) return false;
  try {
    const raw = storage.getItem(HIDE_PHI_KEY);
    return raw === "1" || raw === "true";
  } catch {
    return false;
  }
}

export function writeHidePhi(value: boolean, storage?: Pick<PhiStorage, "setItem"> | null): void {
  if (!storage) return;
  try {
    storage.setItem(HIDE_PHI_KEY, value ? "1" : "0");
  } catch {
    // Private browsing or blocked storage must not break the toggle.
  }
}

/**
 * Label shown for a participant in tables, notices, and dialogs.
 *
 * When `hidePhi` is true, prefers `extRef` (study/external reference), then
 * `fallbackId` (Qualtrics contactId / contactLookupId), and never falls back to
 * `realName`.
 */
export function participantLabel(
  hidePhi: boolean,
  realName: string | null | undefined,
  extRef?: string | null,
  fallbackId?: string | null,
  empty = "(unknown)",
): string {
  const id = (fallbackId ?? "").trim();
  if (!hidePhi) {
    const name = (realName ?? "").trim();
    return name || id || empty;
  }
  const ref = (extRef ?? "").trim();
  return ref || id || "(hidden)";
}

/** Masks a direct PHI string (phone, email, destination) while keeping blanks obvious. */
export function maskPhiText(
  hidePhi: boolean,
  value: string | null | undefined,
  empty = "—",
): string {
  const trimmed = (value ?? "").trim();
  if (!trimmed) return empty;
  return hidePhi ? PHI_MASK : trimmed;
}

/**
 * Sortable table cell value for a direct PHI field. Returning the uniform mask
 * when hidden prevents column sorting from leaking the order of real values.
 */
export function maskPhiCell(
  hidePhi: boolean,
  value: string | null | undefined,
): string | null {
  const trimmed = (value ?? "").trim();
  if (!trimmed) return null;
  return hidePhi ? PHI_MASK : trimmed;
}

/** Core contact fields that carry direct participant PHI. */
export function isPhiCoreField(key: string): boolean {
  return key === "firstName" || key === "lastName" || key === "email" || key === "phone";
}
