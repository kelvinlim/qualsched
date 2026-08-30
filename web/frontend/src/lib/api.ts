/**
 * HTTP client replacing Tauri `invoke` / `listen`.
 *
 * The Qualtrics API token never reaches this file. Every call goes to `/api/...`;
 * the backend talks to `{dc}.qualtrics.com`.
 *
 * Paths are joined with Vite `base` (`import.meta.env.BASE_URL`): `/` for local
 * vite, `/qualsched/` in the production image. Host nginx strips `/qualsched/`
 * so the frontend container still sees `/api/…` / `/auth/…`.
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
} from "@qualsched/ui/lib/types";
import { isNewerVersion } from "@qualsched/ui/lib/version";

/** Copy that differs from the desktop app (server encryption vs keychain). */
export const platformCopy = {
  tokenHint: "Encrypted on the server and never sent back to the browser.",
  tokenRemoved: "Token removed from the server.",
  importTokenHint: "stored encrypted on the server.",
  exportTokenHint: "It stays encrypted on this server, so",
} as const;

export async function openExternalUrl(url: string): Promise<void> {
  window.open(url, "_blank", "noopener");
}

/** Join a root-relative path with Vite `base` (`/` locally, `/qualsched/` in prod). */
export function withBase(path: string): string {
  const base = import.meta.env.BASE_URL || "/";
  const prefix = base.endsWith("/") ? base : `${base}/`;
  const rel = path.startsWith("/") ? path.slice(1) : path;
  return `${prefix}${rel}`;
}

/** Public legal pages Google OAuth branding links to. Null for every other path. */
export function legalKindFromPath(
  pathname = typeof window !== "undefined" ? window.location.pathname : "/",
): "privacy" | "terms" | null {
  const base = import.meta.env.BASE_URL || "/";
  const prefix = base.endsWith("/") ? base.slice(0, -1) : base;
  let path = pathname;
  if (prefix && (path === prefix || path.startsWith(`${prefix}/`))) {
    path = path.slice(prefix.length) || "/";
  }
  const normalized = path.replace(/\/+$/, "") || "/";
  if (normalized === "/privacy") return "privacy";
  if (normalized === "/terms") return "terms";
  return null;
}

export type UnlistenFn = () => void;

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(withBase(path), { credentials: "include", ...init, headers });
  if (res.status === 204) return undefined as T;

  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!res.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body
        ? (body as { detail: unknown }).detail
        : body;
    if (detail && typeof detail === "object" && "message" in detail) {
      throw detail;
    }
    throw {
      kind: "http",
      message: typeof detail === "string" ? detail : res.statusText || `HTTP ${res.status}`,
      retryable: res.status >= 500 && res.status !== 501,
    };
  }

  return body as T;
}

const json = <T>(path: string, method: string, body?: unknown) =>
  request<T>(path, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

// --- config ---------------------------------------------------------------

export const getAppConfig = () => request<AppConfig>("/api/config");

export const saveAccount = (account: Account) =>
  json<AppConfig>("/api/accounts", "POST", account);

export const deleteAccount = (accountId: string) =>
  json<AppConfig>(`/api/accounts/${accountId}`, "DELETE");

export const saveProject = (accountId: string, project: Project) =>
  json<AppConfig>(`/api/accounts/${accountId}/projects`, "POST", project);

export const deleteProject = (accountId: string, projectId: string) =>
  json<AppConfig>(`/api/accounts/${accountId}/projects/${projectId}`, "DELETE");

export const setAccountToken = (accountId: string, token: string) =>
  json<void>(`/api/accounts/${accountId}/token`, "PUT", { token });

export const hasAccountToken = (accountId: string) =>
  request<boolean>(`/api/accounts/${accountId}/has-token`);

export const clearAccountToken = (accountId: string) =>
  json<void>(`/api/accounts/${accountId}/token`, "DELETE");

export const testAccount = (accountId: string) =>
  json<TestResult>(`/api/accounts/${accountId}/test`, "POST");

export const forgetSurveyCopies = (accountId: string, projectId: string) =>
  json<AppConfig>(
    `/api/accounts/${accountId}/projects/${projectId}/forget-copies`,
    "POST",
  );

// --- lookups --------------------------------------------------------------

export const listSurveys = (accountId: string) =>
  request<IdName[]>(`/api/accounts/${accountId}/surveys`);

export const listDirectories = (accountId: string) =>
  request<IdName[]>(`/api/accounts/${accountId}/directories`);

export const listMailingLists = (accountId: string, directoryId: string) =>
  request<MailingListInfo[]>(
    `/api/accounts/${accountId}/mailing-lists?directoryId=${encodeURIComponent(directoryId)}`,
  );

export const listMessages = (accountId: string) =>
  request<MessageInfo[]>(`/api/accounts/${accountId}/messages`);

export const getMessageText = (accountId: string, messageId: string) =>
  request<string>(`/api/accounts/${accountId}/messages/${encodeURIComponent(messageId)}/text`);

// --- contacts (live Qualtrics mailing list; never stored) ---------------

export const getContacts = (accountId: string, projectId: string) =>
  request<ContactView[]>(`/api/accounts/${accountId}/projects/${projectId}/contacts`);

export const createContact = (
  accountId: string,
  projectId: string,
  core: Record<string, string>,
  embedded: Record<string, string>,
) =>
  json<ContactView>(`/api/accounts/${accountId}/projects/${projectId}/contacts`, "POST", {
    core,
    embedded,
  });

export const updateContact = (
  accountId: string,
  projectId: string,
  contactId: string,
  core: Record<string, string>,
  fields: Record<string, string>,
) =>
  json<ContactView>(
    `/api/accounts/${accountId}/projects/${projectId}/contacts/${contactId}`,
    "PUT",
    { core, fields },
  );

export const deleteContact = (
  accountId: string,
  projectId: string,
  contactId: string,
) =>
  json<RemovedContact>(
    `/api/accounts/${accountId}/projects/${projectId}/contacts/${contactId}`,
    "DELETE",
  );

export const applyEmbeddedDefaults = (
  accountId: string,
  projectId: string,
  contactIds: string[],
) =>
  json<ContactView[]>(
    `/api/accounts/${accountId}/projects/${projectId}/contacts/defaults`,
    "POST",
    { contactIds },
  );

// --- scheduling -----------------------------------------------------------

export const previewSchedule = (accountId: string, projectId: string) =>
  json<SchedulePreview>(
    `/api/accounts/${accountId}/projects/${projectId}/schedule/preview`,
    "POST",
  );

export const executeSchedule = (
  accountId: string,
  projectId: string,
  plan: SchedulePreview,
) =>
  json<SendReport>(
    `/api/accounts/${accountId}/projects/${projectId}/schedule/execute`,
    "POST",
    plan,
  );

/** SSE will replace this no-op in a later milestone. */
export const onScheduleProgress = (
  _handler: (p: ScheduleProgress) => void,
): Promise<UnlistenFn> => Promise.resolve(() => {});

// --- distributions --------------------------------------------------------

export const listDistributions = (
  accountId: string,
  projectId: string,
  method: Method,
) =>
  request<DistributionRow[]>(
    `/api/accounts/${accountId}/projects/${projectId}/distributions?method=${method}`,
  );

export const deleteDistributions = (
  accountId: string,
  projectId: string,
  method: Method,
  targets: DeleteTarget[],
) =>
  json<DeleteReport>(
    `/api/accounts/${accountId}/projects/${projectId}/distributions`,
    "DELETE",
    { method, targets },
  );

export const deleteUnsentForContact = (
  accountId: string,
  projectId: string,
  contactId: string,
) =>
  json<DeleteReport>(
    `/api/accounts/${accountId}/projects/${projectId}/distributions/unsent/${contactId}`,
    "DELETE",
  );

export const onDeleteProgress = (
  _handler: (p: { done: number; total: number }) => void,
): Promise<UnlistenFn> => Promise.resolve(() => {});

// --- import / export (file contents, not desktop paths) -------------------

export const previewLegacyImport = (yamlText: string, tokenText?: string, sourceName?: string) => {
  const body = new FormData();
  body.append("yamlText", yamlText);
  body.append("sourceName", sourceName || "config.yaml");
  if (tokenText) body.append("tokenText", tokenText);
  return request<ImportPreview>("/api/import/preview-text", { method: "POST", body });
};

export const confirmLegacyImport = (payload: {
  account: Account;
  project: Project;
  token?: string;
  targetAccountId?: string;
}) => json<AppConfig>("/api/import/confirm", "POST", payload);

export const exportProjectConfig = async (
  accountId: string,
  projectId: string,
  filename: string,
) => {
  const res = await fetch(
    withBase(`/api/accounts/${accountId}/projects/${projectId}/export`),
    { credentials: "include" },
  );
  if (!res.ok) {
    const text = await res.text();
    throw { kind: "http", message: text || res.statusText, retryable: false };
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
};

// --- auth -----------------------------------------------------------------

export interface AuthStatus {
  google: boolean;
  devLogin: boolean;
  version: string;
}

export interface Me {
  id: number;
  email: string;
  name: string | null;
  is_superuser: boolean;
}

export const authStatus = () => request<AuthStatus>("/auth/status");
export const me = () => request<Me>("/auth/me");
export const logout = () => json<{ ok: boolean }>("/auth/logout", "POST");
export const devLogin = (email: string) => json<Me>("/auth/dev-login", "POST", { email });

// --- updates --------------------------------------------------------------

export const checkForUpdate = async (): Promise<UpdateInfo> => {
  const currentVersion = "0.2.1";
  try {
    const res = await fetch(
      "https://api.github.com/repos/kelvinlim/qualsched/releases/latest",
    );
    if (!res.ok) {
      return {
        currentVersion,
        latestVersion: currentVersion,
        updateAvailable: false,
        releaseNotes: "",
        releaseUrl: "https://github.com/kelvinlim/qualsched/releases",
      };
    }
    const rel = (await res.json()) as {
      tag_name?: string;
      body?: string;
      html_url?: string;
    };
    const latestVersion = (rel.tag_name || "").replace(/^v/, "") || currentVersion;
    return {
      currentVersion,
      latestVersion,
      updateAvailable: isNewerVersion(latestVersion, currentVersion),
      releaseNotes: rel.body || "",
      releaseUrl: rel.html_url || "https://github.com/kelvinlim/qualsched/releases",
    };
  } catch {
    throw { kind: "network", message: "Could not reach GitHub.", retryable: true };
  }
};
