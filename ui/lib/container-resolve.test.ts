/**
 * Unit tests for cross-container resolution, labeling, and picker search helpers.
 * Run with `node --experimental-strip-types lib/container-resolve.test.ts`.
 */
import {
  ALL_CONTAINERS,
  effectiveDirectory,
  effectiveMessageLibrary,
  filterPickerOptions,
  formatMailingListLabel,
  formatMessageLabel,
  overrideToSave,
  type PickerItem,
} from "./container-resolve.ts";

function assertEqual(got: unknown, expected: unknown, label: string) {
  const g = JSON.stringify(got);
  const e = JSON.stringify(expected);
  if (g !== e) throw new Error(`${label}: got ${g}, expected ${e}`);
}

// effectiveDirectory resolves profile override or falls back to account default.
assertEqual(
  effectiveDirectory({ defaultDirectory: "POOL_acc" }, { directoryId: "  POOL_prof  " }),
  "POOL_prof",
  "profile directory override wins and trims",
);
assertEqual(
  effectiveDirectory({ defaultDirectory: " POOL_acc " }, { directoryId: "" }),
  "POOL_acc",
  "empty profile directory falls back to account default",
);
assertEqual(
  effectiveDirectory({ defaultDirectory: "POOL_acc" }, { directoryId: "   " }),
  "POOL_acc",
  "whitespace profile directory falls back to account default",
);
assertEqual(
  effectiveDirectory({ defaultDirectory: "POOL_acc" }, {}),
  "POOL_acc",
  "undefined profile directory falls back to account default",
);

// effectiveMessageLibrary resolves SMS and Email libraries independently.
assertEqual(
  effectiveMessageLibrary(
    { libraryId: "GR_acc" },
    { messageLibraryId: "GR_sms", messageEmailLibraryId: "GR_email" },
    "sms",
  ),
  "GR_sms",
  "sms library uses messageLibraryId",
);
assertEqual(
  effectiveMessageLibrary(
    { libraryId: "GR_acc" },
    { messageLibraryId: "GR_sms", messageEmailLibraryId: "GR_email" },
    "email",
  ),
  "GR_email",
  "email library uses messageEmailLibraryId",
);
assertEqual(
  effectiveMessageLibrary(
    { libraryId: " GR_acc " },
    { messageLibraryId: "GR_sms", messageEmailLibraryId: "   " },
    "email",
  ),
  "GR_acc",
  "email falls back independently of sms override",
);
assertEqual(
  effectiveMessageLibrary(
    { libraryId: "GR_acc" },
    { messageEmailLibraryId: "GR_email" },
    "sms",
  ),
  "GR_acc",
  "sms falls back independently of email override",
);

// overrideToSave clears override when blank or matching account default.
assertEqual(overrideToSave("", "POOL_1"), "", "blank selection clears override");
assertEqual(overrideToSave("   ", "POOL_1"), "", "whitespace selection clears override");
assertEqual(
  overrideToSave(" POOL_1 ", "POOL_1"),
  "",
  "matching account default clears override",
);
assertEqual(
  overrideToSave(" POOL_2 ", "POOL_1"),
  "POOL_2",
  "distinct container saves trimmed override",
);

// Label formatting toggles container suffix cleanly.
assertEqual(
  formatMailingListLabel(
    {
      id: "CG_1",
      name: "Cohort A",
      contactCount: 42,
      directoryId: "POOL_2",
      directoryName: "West Lab",
    },
    false,
  ),
  "Cohort A — 42 contacts",
  "mailing list label without container",
);
assertEqual(
  formatMailingListLabel(
    {
      id: "CG_1",
      name: "Cohort A",
      contactCount: null,
      directoryId: "POOL_2",
      directoryName: "West Lab",
    },
    true,
  ),
  "Cohort A · West Lab",
  "mailing list label with container name and null contactCount",
);
assertEqual(
  formatMailingListLabel(
    {
      id: "CG_1",
      name: "Cohort A",
      contactCount: 5,
      directoryId: "POOL_2",
    },
    true,
  ),
  "Cohort A — 5 contacts · POOL_2",
  "mailing list label falls back to directoryId",
);

assertEqual(
  formatMessageLabel(
    {
      id: "MS_1",
      description: "Morning SMS",
      category: "invite",
      libraryId: "GR_2",
      libraryName: "Shared Prompts",
    },
    false,
  ),
  "Morning SMS (MS_1) [invite]",
  "message label without container",
);
assertEqual(
  formatMessageLabel(
    {
      id: "MS_2",
      description: "Evening Email",
      category: null,
      libraryId: "GR_3",
    },
    true,
  ),
  "Evening Email (MS_2) · GR_3",
  "message label with libraryId fallback and null category",
);

// filterPickerOptions handles empty queries and multi-term search across fields.
const items: PickerItem[] = [
  {
    id: "MS_100",
    label: "Daily EMA Prompt (MS_100) [sms] · Core Study",
    name: "Daily EMA Prompt",
    containerId: "GR_1",
    containerName: "Core Study",
    category: "sms",
  },
  {
    id: "MS_200",
    label: "Follow-up Email (MS_200) [invite] · Clinical Team",
    name: "Follow-up Email",
    containerId: "GR_9",
    containerName: "Clinical Team",
    category: "invite",
  },
];

assertEqual(ALL_CONTAINERS, "*", "ALL_CONTAINERS constant");
assertEqual(filterPickerOptions(items, "   ").length, 2, "blank query returns all");
assertEqual(
  filterPickerOptions(items, "core ema").map((x) => x.id),
  ["MS_100"],
  "multi-term matches across containerName and name case-insensitively",
);
assertEqual(
  filterPickerOptions(items, "GR_9 INVITE").map((x) => x.id),
  ["MS_200"],
  "matches across containerId and category",
);
assertEqual(
  filterPickerOptions(items, "ms_100").map((x) => x.id),
  ["MS_100"],
  "matches id case-insensitively",
);
assertEqual(
  filterPickerOptions(items, "nonexistent term"),
  [],
  "unmatched query returns empty list",
);
