import * as api from "./api";
import type { Account, AppConfig, Project } from "./types";

export type ScreenName =
  | "accounts"
  | "project"
  | "contacts"
  | "schedule"
  | "distributions"
  | "import"
  | "guide";

/** The backend owns the config; this mirrors whatever it last returned. */
class AppStore {
  config = $state<AppConfig>({ version: 1, accounts: [] });
  selectedAccountId = $state<string | null>(null);
  selectedProjectId = $state<string | null>(null);
  screen = $state<ScreenName>("accounts");
  loaded = $state(false);

  get account(): Account | null {
    return this.config.accounts.find((a) => a.id === this.selectedAccountId) ?? null;
  }

  get project(): Project | null {
    return this.account?.projects.find((p) => p.id === this.selectedProjectId) ?? null;
  }

  /** True when a screen that needs both an account and a project can be opened. */
  get hasProject(): boolean {
    return this.account !== null && this.project !== null;
  }

  async load() {
    this.config = await api.getAppConfig();
    this.loaded = true;
    if (!this.account && this.config.accounts.length > 0) {
      this.select(this.config.accounts[0].id);
    }
  }

  /** Applies a config the backend just returned, keeping the selection valid. */
  apply(config: AppConfig) {
    this.config = config;
    if (this.selectedAccountId && !this.account) {
      this.selectedAccountId = config.accounts[0]?.id ?? null;
      this.selectedProjectId = null;
    }
    if (this.selectedProjectId && !this.project) {
      this.selectedProjectId = this.account?.projects[0]?.id ?? null;
    }
  }

  select(accountId: string | null, projectId: string | null = null) {
    this.selectedAccountId = accountId;
    this.selectedProjectId =
      projectId ??
      (accountId
        ? (this.config.accounts.find((a) => a.id === accountId)?.projects[0]?.id ?? null)
        : null);
  }

  go(screen: ScreenName) {
    this.screen = screen;
  }
}

export const app = new AppStore();

export function newProject(name = "New project"): Project {
  return {
    id: crypto.randomUUID(),
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

export function newAccount(name = "New account"): Account {
  return {
    id: crypto.randomUUID(),
    name,
    dataCenter: "",
    verifyTls: true,
    defaultDirectory: "",
    libraryId: "",
    projects: [],
  };
}
