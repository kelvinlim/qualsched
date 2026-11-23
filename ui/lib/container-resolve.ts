/**
 * Effective container resolution, labeling, and picker search helpers for Qualtrics
 * directories (mailing lists) and message libraries (SMS & email templates). Pure: no
 * browser storage and no network.
 */
import type {
  Account,
  MailingListInfo,
  MessageInfo,
  Method,
  Project,
} from "./types";

export const ALL_CONTAINERS = "*";

export interface PickerItem {
  id: string;
  label: string;
  name?: string;
  containerId: string;
  containerName?: string;
  category?: string | null;
}

export function effectiveDirectory(
  account: Pick<Account, "defaultDirectory">,
  project: Pick<Project, "directoryId">,
): string {
  return (project.directoryId ?? "").trim() || account.defaultDirectory.trim();
}

export function effectiveMessageLibrary(
  account: Pick<Account, "libraryId">,
  project: Pick<Project, "messageLibraryId" | "messageEmailLibraryId">,
  method: Method,
): string {
  const override =
    method === "email"
      ? (project.messageEmailLibraryId ?? "")
      : (project.messageLibraryId ?? "");
  return override.trim() || account.libraryId.trim();
}

export function overrideToSave(selectedContainerId: string, accountDefaultId: string): string {
  const trimmed = selectedContainerId.trim();
  if (!trimmed || trimmed === accountDefaultId.trim()) return "";
  return trimmed;
}

export function formatMailingListLabel(item: MailingListInfo, showContainer: boolean): string {
  const count = item.contactCount === null ? "" : ` — ${item.contactCount} contacts`;
  const container =
    showContainer && (item.directoryName || item.directoryId)
      ? ` · ${item.directoryName || item.directoryId}`
      : "";
  return `${item.name}${count}${container}`;
}

export function formatMessageLabel(item: MessageInfo, showContainer: boolean): string {
  const cat = item.category ? ` [${item.category}]` : "";
  const container =
    showContainer && (item.libraryName || item.libraryId)
      ? ` · ${item.libraryName || item.libraryId}`
      : "";
  return `${item.description} (${item.id})${cat}${container}`;
}

export function filterPickerOptions<T extends PickerItem>(options: T[], query: string): T[] {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return options;
  return options.filter((opt) => {
    const fields = [
      opt.id,
      opt.label,
      opt.name ?? "",
      opt.containerId,
      opt.containerName ?? "",
      opt.category ?? "",
    ].map((f) => f.toLowerCase());
    return terms.every((term) => fields.some((field) => field.includes(term)));
  });
}
