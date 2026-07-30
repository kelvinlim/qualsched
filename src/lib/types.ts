export interface AppConfig {
  version: number;
  accounts: Account[];
}

export interface Account {
  id: string;
  name: string;
  dataCenter: string;
  verifyTls: boolean;
  defaultDirectory: string;
  libraryId: string;
  projects: Project[];
}

export interface Project {
  id: string;
  name: string;
  surveyId: string;
  messageId: string;
  messageIdEmail: string;
  mailingListId: string;
  timezone: string;
  minutesExpire: number;
  emailHeader: EmailHeader;
  embeddedDefaults: EmbeddedDefaults;
  /** Clones of surveyId recorded by 0.1.4. Nothing writes these now; they are kept so their
   * pending invitations stay cancellable, and cleared by forgetSurveyCopies. */
  surveyCopies: SurveyCopy[];
  copiesSourceSurveyId: string;
}

export interface SurveyCopy {
  id: string;
  name: string;
}

export interface EmailHeader {
  fromEmail: string;
  fromName: string;
  replyToEmail: string;
  subject: string;
}

export interface EmbeddedDefaults {
  startDate: string;
  surveysScheduled: number;
  timeSlots: string;
  contactMethod: string;
  deleteUnsent: number;
  numDays: number;
  expireMinutes: number;
  logData: string;
  timeZone: string;
}

export interface IdName {
  id: string;
  name: string;
}

export interface MailingListInfo {
  id: string;
  name: string;
  contactCount: number | null;
}

export interface MessageInfo {
  id: string;
  description: string;
  category: string | null;
}

export interface ContactView {
  contactId: string;
  firstName: string;
  lastName: string;
  email: string;
  phone: string;
  extRef: string;
  embedded: Record<string, string>;
  eligible: boolean;
  skipReason: string | null;
  method: string | null;
}

export type Method = "sms" | "email";

export interface PlanItem {
  contactId: string;
  contactName: string;
  destination: string;
  method: Method;
  dayIndex: number;
  slotLabel: string;
  /** The survey this item sends through — always the profile's own. */
  surveyId: string;
  surveyLabel: string;
  sendLocal: string;
  sendUtc: string;
  expireUtc: string;
}

export interface Skipped {
  contactId: string;
  contactName: string;
  reason: string;
}

export interface SchedulePreview {
  items: PlanItem[];
  skippedContacts: Skipped[];
  skippedSlots: Skipped[];
  /** Things to tell the user before they approve the plan. */
  warnings: string[];
}

export interface ItemFailure {
  contactName: string;
  destination: string;
  sendLocal: string;
  error: string;
  retryable: boolean;
}

export interface SendReport {
  scheduled: number;
  failed: ItemFailure[];
  bookkeepingFailures: ItemFailure[];
}

export interface DistributionRow {
  id: string;
  contactLookupId: string;
  contactName: string;
  sendDate: string;
  /** Wall-clock time in the recipient's own timezone; empty when it is unknown. */
  sendLocal: string;
  method: Method;
  unsent: boolean;
  /** Needed to cancel the row: a 0.1.4 clone's distribution can't be cancelled with the
   * profile's own survey id. */
  surveyId: string;
  surveyLabel: string;
}

/** One row to cancel, paired with the survey it was created against. */
export interface DeleteTarget {
  id: string;
  surveyId: string;
}

export interface RemovedContact {
  contactName: string;
  /** Pending invitations withdrawn before the participant was removed. */
  cancelled: number;
}

export interface DeleteReport {
  deleted: number;
  failed: { id: string; error: string }[];
}

export interface TestResult {
  ok: boolean;
  message: string;
  directoryCount: number;
}

export interface ImportPreview {
  account: Account;
  project: Project;
  warnings: string[];
  tokenFound: boolean;
}

export interface ScheduleProgress {
  done: number;
  total: number;
  contactName: string;
  ok: boolean;
}

/** Shape every rejected `invoke` takes — see AppError's Serialize impl in Rust. */
export interface AppError {
  kind: string;
  message: string;
  retryable: boolean;
}

export function errorMessage(e: unknown): string {
  if (e && typeof e === "object" && "message" in e) {
    return String((e as AppError).message);
  }
  return String(e);
}
