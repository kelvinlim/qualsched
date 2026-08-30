import type { AppConfig, Project } from "./types";

/**
 * Append `project` onto the named account's `projects`. Local config only —
 * same shape as `addAccount` (`{ ...config, accounts: [...] }`); does not persist.
 */
export function withAddedProject(
  config: AppConfig,
  accountId: string,
  project: Project,
): AppConfig {
  return {
    ...config,
    accounts: config.accounts.map((account) =>
      account.id === accountId
        ? { ...account, projects: [...account.projects, project] }
        : account,
    ),
  };
}

/** Resolve the selected project the same way `app.project` does. */
export function projectAt(
  config: AppConfig,
  accountId: string | null,
  projectId: string | null,
): Project | null {
  if (!accountId || !projectId) return null;
  const account = config.accounts.find((a) => a.id === accountId);
  return account?.projects.find((p) => p.id === projectId) ?? null;
}
