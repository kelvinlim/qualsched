import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

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
} from "./types";

// --- config ---------------------------------------------------------------

export const getAppConfig = () => invoke<AppConfig>("get_app_config");

export const saveAccount = (account: Account) =>
  invoke<AppConfig>("save_account", { account });

export const deleteAccount = (accountId: string) =>
  invoke<AppConfig>("delete_account", { accountId });

export const saveProject = (accountId: string, project: Project) =>
  invoke<AppConfig>("save_project", { accountId, project });

export const deleteProject = (accountId: string, projectId: string) =>
  invoke<AppConfig>("delete_project", { accountId, projectId });

export const setAccountToken = (accountId: string, token: string) =>
  invoke<void>("set_account_token", { accountId, token });

export const hasAccountToken = (accountId: string) =>
  invoke<boolean>("has_account_token", { accountId });

export const clearAccountToken = (accountId: string) =>
  invoke<void>("clear_account_token", { accountId });

export const testAccount = (accountId: string) =>
  invoke<TestResult>("test_account", { accountId });

/** Drops the record of the clones 0.1.4 made; the surveys themselves stay in Qualtrics. */
export const forgetSurveyCopies = (accountId: string, projectId: string) =>
  invoke<AppConfig>("forget_survey_copies", { accountId, projectId });

// --- lookups --------------------------------------------------------------

export const listSurveys = (accountId: string) =>
  invoke<IdName[]>("list_surveys", { accountId });

export const listDirectories = (accountId: string) =>
  invoke<IdName[]>("list_directories", { accountId });

export const listMailingLists = (accountId: string, directoryId: string) =>
  invoke<MailingListInfo[]>("list_mailing_lists", { accountId, directoryId });

export const listMessages = (accountId: string) =>
  invoke<MessageInfo[]>("list_messages", { accountId });

export const getMessageText = (accountId: string, messageId: string) =>
  invoke<string>("get_message_text", { accountId, messageId });

// --- contacts -------------------------------------------------------------

export const getContacts = (accountId: string, projectId: string) =>
  invoke<ContactView[]>("get_contacts", { accountId, projectId });

export const createContact = (
  accountId: string,
  projectId: string,
  core: Record<string, string>,
  embedded: Record<string, string>,
) =>
  invoke<ContactView>("create_contact", { accountId, projectId, core, embedded });

export const updateContact = (
  accountId: string,
  projectId: string,
  contactId: string,
  core: Record<string, string>,
  fields: Record<string, string>,
) =>
  invoke<ContactView>("update_contact", {
    accountId,
    projectId,
    contactId,
    core,
    fields,
  });

export const deleteContact = (
  accountId: string,
  projectId: string,
  contactId: string,
) => invoke<RemovedContact>("delete_contact", { accountId, projectId, contactId });

export const applyEmbeddedDefaults = (
  accountId: string,
  projectId: string,
  contactIds: string[],
) =>
  invoke<ContactView[]>("apply_embedded_defaults", {
    accountId,
    projectId,
    contactIds,
  });

// --- scheduling -----------------------------------------------------------

export const previewSchedule = (accountId: string, projectId: string) =>
  invoke<SchedulePreview>("preview_schedule", { accountId, projectId });

export const executeSchedule = (
  accountId: string,
  projectId: string,
  plan: SchedulePreview,
) => invoke<SendReport>("execute_schedule", { accountId, projectId, plan });

export const onScheduleProgress = (
  handler: (p: ScheduleProgress) => void,
): Promise<UnlistenFn> =>
  listen<ScheduleProgress>("schedule://progress", (e) => handler(e.payload));

// --- distributions --------------------------------------------------------

export const listDistributions = (
  accountId: string,
  projectId: string,
  method: Method,
) => invoke<DistributionRow[]>("list_distributions", { accountId, projectId, method });

export const deleteDistributions = (
  accountId: string,
  projectId: string,
  method: Method,
  targets: DeleteTarget[],
) =>
  invoke<DeleteReport>("delete_distributions", {
    accountId,
    projectId,
    method,
    targets,
  });

export const deleteUnsentForContact = (
  accountId: string,
  projectId: string,
  contactId: string,
) =>
  invoke<DeleteReport>("delete_unsent_for_contact", {
    accountId,
    projectId,
    contactId,
  });

export const onDeleteProgress = (
  handler: (p: { done: number; total: number }) => void,
): Promise<UnlistenFn> =>
  listen<{ done: number; total: number }>("distributions://progress", (e) =>
    handler(e.payload),
  );

// --- import ---------------------------------------------------------------

export const previewLegacyImport = (yamlPath: string, tokenPath?: string) =>
  invoke<ImportPreview>("preview_legacy_import", { yamlPath, tokenPath });

export const confirmLegacyImport = (request: {
  account: Account;
  project: Project;
  token?: string;
  tokenPath?: string;
  /** Set to add the profile to an account that already exists; its settings and stored
   * token are left untouched and the file's account block is discarded. */
  targetAccountId?: string;
}) => invoke<AppConfig>("confirm_legacy_import", { request });
