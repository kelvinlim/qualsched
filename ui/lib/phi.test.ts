/**
 * Unit tests for Hide PHI formatting and persistence.
 * Run with `node --experimental-strip-types lib/phi.test.ts`.
 */
import {
  HIDE_PHI_KEY,
  PHI_MASK,
  isPhiCoreField,
  maskPhiCell,
  maskPhiText,
  participantLabel,
  readHidePhi,
  writeHidePhi,
} from "./phi.ts";

function assertEqual(got: unknown, expected: unknown, label: string) {
  const g = JSON.stringify(got);
  const e = JSON.stringify(expected);
  if (g !== e) throw new Error(`${label}: got ${g}, expected ${e}`);
}

// Defaults to false when unset or unavailable.
assertEqual(readHidePhi(null), false, "no storage defaults false");
const mem = new Map<string, string>();
const store = {
  getItem: (k: string) => mem.get(k) ?? null,
  setItem: (k: string, v: string) => {
    mem.set(k, v);
  },
};
assertEqual(readHidePhi(store), false, "empty storage defaults false");

writeHidePhi(true, store);
assertEqual(mem.get(HIDE_PHI_KEY), "1", "persists enabled flag");
assertEqual(readHidePhi(store), true, "reads enabled flag");

writeHidePhi(false, store);
assertEqual(mem.get(HIDE_PHI_KEY), "0", "persists disabled flag");
assertEqual(readHidePhi(store), false, "reads disabled flag");

const throwingStore = {
  getItem: () => {
    throw new Error("blocked");
  },
  setItem: () => {
    throw new Error("blocked");
  },
};
assertEqual(readHidePhi(throwingStore), false, "throwing getItem falls back to false");
writeHidePhi(true, throwingStore);

// Participant label resolution.
assertEqual(
  participantLabel(false, "Ada Lovelace", "su-1361", "CID_ada"),
  "Ada Lovelace",
  "unhidden prefers real name",
);
assertEqual(
  participantLabel(false, "", "su-1361", "CID_ada"),
  "CID_ada",
  "unhidden falls back to id when name is empty",
);
assertEqual(
  participantLabel(true, "Ada Lovelace", "su-1361", "CID_ada"),
  "su-1361",
  "hidden prefers extRef over contactId",
);
assertEqual(
  participantLabel(true, "Ada Lovelace", "   ", "CID_ada"),
  "CID_ada",
  "hidden falls back to contactId when extRef is blank",
);
assertEqual(
  participantLabel(true, "Ada Lovelace", "", ""),
  "(hidden)",
  "hidden never leaks realName when both extRef and id are absent",
);

// Masking direct PHI values.
assertEqual(maskPhiText(false, "+16125551234"), "+16125551234", "unhidden phone");
assertEqual(maskPhiText(true, "+16125551234"), PHI_MASK, "hidden phone masked");
assertEqual(maskPhiText(true, ""), "—", "hidden empty stays em-dash");
assertEqual(maskPhiCell(true, "ada@example.org"), PHI_MASK, "hidden cell masked uniformly");
assertEqual(maskPhiCell(true, "   "), null, "hidden blank cell is null");
assertEqual(maskPhiCell(false, "ada@example.org"), "ada@example.org", "unhidden cell kept");

// Core field classification.
assertEqual(isPhiCoreField("firstName"), true, "firstName is PHI");
assertEqual(isPhiCoreField("lastName"), true, "lastName is PHI");
assertEqual(isPhiCoreField("email"), true, "email is PHI");
assertEqual(isPhiCoreField("phone"), true, "phone is PHI");
assertEqual(isPhiCoreField("extRef"), false, "extRef is not masked");

console.log("phi tests ok");
