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
  method: Method;
  unsent: boolean;
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
