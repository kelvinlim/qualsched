/**
 * Type-only stand-in for `@qualsched/api` so `ui` can typecheck without an app.
 * Desktop and web Vite configs resolve the alias to their real `lib/api.ts`.
 */
import type {
  Account,
  AppConfig,
  ContactView,
  DeleteReport,
  DeleteTarget,
  DistributionRow,
  IdName,
  ImportPreview,
  MailingListInfo,
  MessageInfo,
  Method,
  Project,
  RemovedContact,
  ScheduleProgress,
  SchedulePreview,
  SendReport,
  TestResult,
  UpdateInfo,
} from "./types";

export type UnlistenFn = () => void;

export const platformCopy: {
  tokenHint: string;
  tokenRemoved: string;
  importTokenHint: string;
  exportTokenHint: string;
} = {
  tokenHint: "",
  tokenRemoved: "",
  importTokenHint: "",
  exportTokenHint: "",
};

export const openExternalUrl: (url: string) => Promise<void> = async () => {};

export const getAppConfig: () => Promise<AppConfig> = async () => ({
  version: 1,
  accounts: [],
});
export const saveAccount: (account: Account) => Promise<AppConfig> = async () =>
  getAppConfig();
export const deleteAccount: (accountId: string) => Promise<AppConfig> = async () =>
  getAppConfig();
export const saveProject: (accountId: string, project: Project) => Promise<AppConfig> =
  async () => getAppConfig();
export const deleteProject: (
  accountId: string,
  projectId: string,
) => Promise<AppConfig> = async () => getAppConfig();
export const setAccountToken: (accountId: string, token: string) => Promise<void> =
  async () => {};
export const hasAccountToken: (accountId: string) => Promise<boolean> = async () => false;
export const clearAccountToken: (accountId: string) => Promise<void> = async () => {};
export const testAccount: (accountId: string) => Promise<TestResult> = async () => ({
  ok: false,
  message: "",
  directoryCount: 0,
});
export const forgetSurveyCopies: (
  accountId: string,
  projectId: string,
) => Promise<AppConfig> = async () => getAppConfig();

export const listSurveys: (accountId: string) => Promise<IdName[]> = async () => [];
export const listDirectories: (accountId: string) => Promise<IdName[]> = async () => [];
export const listMailingLists: (
  accountId: string,
  directoryId: string,
) => Promise<MailingListInfo[]> = async () => [];
export const listMessages: (accountId: string) => Promise<MessageInfo[]> = async () => [];
export const getMessageText: (accountId: string, messageId: string) => Promise<string> =
  async () => "";

export const getContacts: (
  accountId: string,
  projectId: string,
) => Promise<ContactView[]> = async () => [];
export const createContact: (
  accountId: string,
  projectId: string,
  core: Record<string, string>,
  embedded: Record<string, string>,
) => Promise<ContactView> = async () => ({
  contactId: "",
  firstName: "",
  lastName: "",
  email: "",
  phone: "",
  extRef: "",
  embedded: {},
  eligible: false,
  skipReason: null,
  method: null,
});
export const updateContact: (
  accountId: string,
  projectId: string,
  contactId: string,
  core: Record<string, string>,
  fields: Record<string, string>,
) => Promise<ContactView> = async () => createContact("", "", {}, {});
export const deleteContact: (
  accountId: string,
  projectId: string,
  contactId: string,
) => Promise<RemovedContact> = async () => ({ contactName: "", cancelled: 0 });
export const applyEmbeddedDefaults: (
  accountId: string,
  projectId: string,
  contactIds: string[],
) => Promise<ContactView[]> = async () => [];

export const previewSchedule: (
  accountId: string,
  projectId: string,
) => Promise<SchedulePreview> = async () => ({
  items: [],
  skippedContacts: [],
  skippedSlots: [],
  warnings: [],
});
export const executeSchedule: (
  accountId: string,
  projectId: string,
  plan: SchedulePreview,
) => Promise<SendReport> = async () => ({
  scheduled: 0,
  failed: [],
  bookkeepingFailures: [],
});
export const onScheduleProgress: (
  handler: (p: ScheduleProgress) => void,
) => Promise<UnlistenFn> = async () => () => {};

export const listDistributions: (
  accountId: string,
  projectId: string,
  method: Method,
) => Promise<DistributionRow[]> = async () => [];
export const deleteDistributions: (
  accountId: string,
  projectId: string,
  method: Method,
  targets: DeleteTarget[],
) => Promise<DeleteReport> = async () => ({ deleted: 0, failed: [] });
export const deleteUnsentForContact: (
  accountId: string,
  projectId: string,
  contactId: string,
) => Promise<DeleteReport> = async () => ({ deleted: 0, failed: [] });
export const onDeleteProgress: (
  handler: (p: { done: number; total: number }) => void,
) => Promise<UnlistenFn> = async () => () => {};

export const previewLegacyImport: (
  yamlText: string,
  tokenText?: string,
  sourceName?: string,
) => Promise<ImportPreview> = async () => ({
  account: {
    id: "",
    name: "",
    dataCenter: "",
    verifyTls: true,
    defaultDirectory: "",
    libraryId: "",
    projects: [],
  },
  project: {
    id: "",
    name: "",
    surveyId: "",
    messageId: "",
    messageIdEmail: "",
    mailingListId: "",
    timezone: "",
    minutesExpire: 60,
    emailHeader: { fromEmail: "", fromName: "", replyToEmail: "", subject: "" },
    embeddedDefaults: {
      startDate: "",
      surveysScheduled: 0,
      timeSlots: "",
      contactMethod: "",
      deleteUnsent: 0,
      numDays: 0,
      expireMinutes: 60,
      logData: "[]",
      timeZone: "",
    },
    surveyCopies: [],
    copiesSourceSurveyId: "",
  },
  warnings: [],
  tokenFound: false,
});
export const confirmLegacyImport: (payload: {
  account: Account;
  project: Project;
  token?: string;
  tokenPath?: string;
  targetAccountId?: string;
}) => Promise<AppConfig> = async () => getAppConfig();
export const exportProjectConfig: (
  accountId: string,
  projectId: string,
  filename: string,
) => Promise<void> = async () => {};

export const checkForUpdate: () => Promise<UpdateInfo> = async () => ({
  currentVersion: "",
  latestVersion: "",
  updateAvailable: false,
  releaseNotes: "",
  releaseUrl: "",
});
