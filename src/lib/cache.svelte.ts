import * as api from "./api";
import type { IdName, MailingListInfo, MessageInfo } from "./types";

const TTL_MS = 5 * 60 * 1000;

interface Entry<T> {
  value: T;
  at: number;
}

/**
 * Caches dropdown data per account so opening a form does not re-hit the API on every
 * render, and de-duplicates concurrent loads of the same key.
 */
class LookupCache {
  #entries = new Map<string, Entry<unknown>>();
  #inflight = new Map<string, Promise<unknown>>();

  async get<T>(key: string, loader: () => Promise<T>, force = false): Promise<T> {
    if (!force) {
      const hit = this.#entries.get(key);
      if (hit && Date.now() - hit.at < TTL_MS) return hit.value as T;
      const pending = this.#inflight.get(key);
      if (pending) return pending as Promise<T>;
    }

    const load = loader()
      .then((value) => {
        this.#entries.set(key, { value, at: Date.now() });
        return value;
      })
      .finally(() => this.#inflight.delete(key));

    this.#inflight.set(key, load);
    return load;
  }

  /** Drops everything for one account — used after its token or data center changes. */
  invalidateAccount(accountId: string) {
    for (const key of [...this.#entries.keys()]) {
      if (key.startsWith(`${accountId}:`)) this.#entries.delete(key);
    }
  }
}

const cache = new LookupCache();

export const surveys = (accountId: string, force = false) =>
  cache.get<IdName[]>(`${accountId}:surveys`, () => api.listSurveys(accountId), force);

export const directories = (accountId: string, force = false) =>
  cache.get<IdName[]>(`${accountId}:directories`, () => api.listDirectories(accountId), force);

export const mailingLists = (accountId: string, directoryId: string, force = false) =>
  cache.get<MailingListInfo[]>(
    `${accountId}:lists:${directoryId}`,
    () => api.listMailingLists(accountId, directoryId),
    force,
  );

export const messages = (accountId: string, force = false) =>
  cache.get<MessageInfo[]>(`${accountId}:messages`, () => api.listMessages(accountId), force);

export const invalidateAccount = (accountId: string) => cache.invalidateAccount(accountId);
