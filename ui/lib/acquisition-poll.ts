/** Browser-side follow-up for an acquisition export. One slice must finish or fail. */

export const ACQUISITION_SLICE_MS = 50_000;
/** Status reads return immediately, so this is a wall-clock budget.
 * 600 pauses of 1.5s is 15 minutes. That outlasts contact listing plus the
 * server's 8-minute export deadline, so the page does not abandon a live export. */
export const ACQUISITION_MAX_SLICES = 600;
export const ACQUISITION_PAUSE_MS = 1_500;

const PENDING_STAGES = new Set(["start", "poll", "download", "parse"]);

const STATUS_EXACT = new Set([
  "Connecting to Qualtrics",
  "Loading contacts",
  "Contacts loaded",
  "Loading invitations",
  "Invitations loaded",
  "Counting completions",
]);

const STATUS_PROGRESS =
  /^(Exporting survey|Waiting for export|Downloading export) [1-9]\d{0,2} of [1-9]\d{0,2}$/;

/** A status line the server is allowed to show. Anything else is dropped. */
export function acquisitionStatus(value: unknown): string | null {
  if (typeof value !== "string") return null;
  if (STATUS_EXACT.has(value) || STATUS_PROGRESS.test(value)) return value;
  return null;
}

/** Desktop events share one channel. Only the attempt that owns this load is shown. */
export function acquisitionEventStatus(payload: unknown, attempt: string): string | null {
  if (!payload || typeof payload !== "object") return null;
  const row = payload as { status?: unknown; attempt?: unknown };
  if (row.attempt !== attempt) return null;
  return acquisitionStatus(row.status);
}

export interface AcquisitionPollError {
  kind: string;
  message: string;
  retryable: boolean;
}

function sliceTimeout(): AcquisitionPollError {
  return {
    kind: "timeout",
    message: "The acquisition request did not answer within 50 seconds.",
    retryable: true,
  };
}

function pollTimeout(): AcquisitionPollError {
  return {
    kind: "timeout",
    message: "Qualtrics response export failed at poll (timeout).",
    retryable: true,
  };
}

function httpFailure(status: number): AcquisitionPollError {
  return {
    kind: "http",
    message: `Acquisition request failed (HTTP ${status}).`,
    retryable: status >= 500 && status !== 501,
  };
}

export async function followAcquisition(options: {
  request: (signal: AbortSignal) => Promise<Response>;
  signal?: AbortSignal;
  pause?: (ms: number, signal?: AbortSignal) => Promise<void>;
  sliceMs?: number;
  maxSlices?: number;
  pauseMs?: number;
  onStatus?: (status: string) => void;
}): Promise<unknown> {
  const pause = options.pause ?? defaultPause;
  const sliceMs = options.sliceMs ?? ACQUISITION_SLICE_MS;
  const maxSlices = options.maxSlices ?? ACQUISITION_MAX_SLICES;
  const pauseMs = options.pauseMs ?? ACQUISITION_PAUSE_MS;
  for (let slice = 0; slice < maxSlices; slice += 1) {
    if (options.signal?.aborted) {
      throw new DOMException("aborted", "AbortError");
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), sliceMs);
    const abortSlice = () => controller.abort();
    options.signal?.addEventListener("abort", abortSlice);
    let response: Response;
    try {
      response = await options.request(controller.signal);
    } catch (error) {
      if (options.signal?.aborted) throw error;
      if (controller.signal.aborted) throw sliceTimeout();
      throw error;
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener("abort", abortSlice);
    }
    const text = await response.text();
    let body: unknown = null;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = null;
      }
    }
    if (response.status === 202) {
      const stage =
        body && typeof body === "object" && "pending" in body
          ? String((body as { stage?: unknown }).stage)
          : "";
      if (PENDING_STAGES.has(stage)) {
        const status = acquisitionStatus(
          body && typeof body === "object" && "status" in body
            ? (body as { status?: unknown }).status
            : null,
        );
        if (status) options.onStatus?.(status);
        await pause(pauseMs, options.signal);
        continue;
      }
      throw {
        kind: "http",
        message: "Qualtrics response export failed at poll.",
        retryable: true,
      };
    }
    if (!response.ok) {
      const detail =
        body && typeof body === "object" && "detail" in body
          ? (body as { detail: unknown }).detail
          : null;
      if (
        detail &&
        typeof detail === "object" &&
        "message" in detail &&
        typeof (detail as { message: unknown }).message === "string"
      ) {
        throw detail;
      }
      throw httpFailure(response.status);
    }
    return body;
  }
  throw pollTimeout();
}

function defaultPause(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("aborted", "AbortError"));
      return;
    }
    const id = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(id);
        reject(new DOMException("aborted", "AbortError"));
      },
      { once: true },
    );
  });
}
