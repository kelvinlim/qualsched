/**
 * Tiny runner for add-profile config updates. Invoked with
 * `node --experimental-strip-types lib/project.test.ts` so we do not add a
 * frontend test framework. Relative `.ts` import is for Node ESM.
 */
import { projectAt, withAddedProject } from "./project.ts";
import type { Account, AppConfig, Project } from "./types.ts";

function assertEqual(got: unknown, expected: unknown, label: string) {
  const g = JSON.stringify(got);
  const e = JSON.stringify(expected);
  if (g !== e) {
    throw new Error(`${label}: got ${g}, expected ${e}`);
  }
}

function stubProject(id: string, name = "New project"): Project {
  return {
    id,
    name,
    surveyId: "",
    messageId: "",
    messageIdEmail: "",
    mailingListId: "",
    timezone: "America/Chicago",
    minutesExpire: 60,
    emailHeader: {
      fromEmail: "noreply@qualtrics.com",
      fromName: "Qualtrics",
      replyToEmail: "noreply@qualtrics.com",
      subject: "Survey",
    },
    embeddedDefaults: {
      startDate: "",
      surveysScheduled: 0,
      timeSlots: "800,1200,1600,2000",
      contactMethod: "sms",
      deleteUnsent: 0,
      numDays: 0,
      expireMinutes: 60,
      logData: "[]",
      timeZone: "America/Chicago",
    },
    surveyCopies: [],
    copiesSourceSurveyId: "",
  };
}

function stubAccount(id: string, projects: Project[]): Account {
  return {
    id,
    name: "kolim-umn",
    dataCenter: "yu1",
    verifyTls: true,
    defaultDirectory: "",
    libraryId: "",
    projects,
  };
}

const existing = stubProject("p-existing", "config 314ema");
const account = stubAccount("acc-1", [existing]);
const config: AppConfig = { version: 1, accounts: [account] };

const added = stubProject("p-new");
// addProject-equivalent: apply(withAddedProject(...)) then select(accountId, project.id)
const next = withAddedProject(config, account.id, added);
const selectedAccountId = account.id;
const selectedProjectId = added.id;

assertEqual(
  next.accounts.find((a) => a.id === account.id)?.projects.map((p) => p.id),
  ["p-existing", "p-new"],
  "new id is in account.projects",
);
assertEqual(
  projectAt(next, selectedAccountId, selectedProjectId)?.id,
  "p-new",
  "new id is the selected project",
);
assertEqual(
  projectAt(config, selectedAccountId, selectedProjectId),
  null,
  "original config is not mutated",
);
assertEqual(
  next.accounts.find((a) => a.id === account.id)?.projects[0].id,
  "p-existing",
  "existing profiles stay in the list",
);

console.log("add profile: 4 checks passed");
