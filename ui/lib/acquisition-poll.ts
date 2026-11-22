/** Browser-side follow-up for an acquisition export. One slice must finish or fail. */

export const ACQUISITION_SLICE_MS = 50_000;
export const ACQUISITION_MAX_SLICES = 240;
export const ACQUISITION_PAUSE_MS = 1_500;

const PENDING_STAGES = new Set(["start", "poll", "download", "parse"]);

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
    if (
      response.status === 202 &&
      body &&
      typeof body === "object" &&
      "pending" in body &&
      PENDING_STAGES.has(String((body as { stage?: unknown }).stage))
    ) {
      await pause(pauseMs, options.signal);
      continue;
    }
    if (!response.ok) {
      const detail =
        body && typeof body === "object" && "detail" in body
          ? (body as { detail: unknown }).detail
          : null;
      if (detail && typeof detail === "object" && "message" in detail) {
        const message = String((detail as { message: unknown }).message);
        if (message.startsWith("Qualtrics response export failed at ")) throw detail;
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
