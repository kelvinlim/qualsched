import {
  ACQUISITION_MAX_SLICES,
  ACQUISITION_PAUSE_MS,
  acquisitionEventStatus,
  acquisitionStatus,
  followAcquisition,
} from "./acquisition-poll.ts";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

let slices = 0;
const calls: string[] = [];

const pendingThenDone = async (signal: AbortSignal) => {
  if (signal.aborted) throw new DOMException("aborted", "AbortError");
  calls.push("request");
  slices += 1;
  if (slices < 3) return jsonResponse(202, { pending: true, stage: "poll" });
  return jsonResponse(200, { rows: [{ displayName: "Ada Lovelace" }] });
};

const report = await followAcquisition({
  request: pendingThenDone,
  pause: async () => {},
});
if ((report as { rows: { displayName: string }[] }).rows[0].displayName !== "Ada Lovelace") {
  throw new Error("poll should return the finished report");
}
if (calls.length !== 3) throw new Error(`expected 3 requests, got ${calls.length}`);

let hung = 0;
try {
  await followAcquisition({
    request: async () => {
      hung += 1;
      return jsonResponse(202, { pending: true, stage: "download" });
    },
    pause: async () => {},
    maxSlices: 2,
  });
  throw new Error("endless progress should stop");
} catch (error) {
  const message = (error as { message?: string }).message ?? "";
  if (message !== "Qualtrics response export failed at poll (timeout).") throw error;
  if (hung !== 2) throw new Error(`expected 2 slices, got ${hung}`);
}

try {
  await followAcquisition({
    request: async () =>
      new Response("<html>secret-symptom gateway</html>", { status: 504 }),
    pause: async () => {},
  });
  throw new Error("gateway failure should throw");
} catch (error) {
  const message = (error as { message?: string }).message ?? "";
  if (message !== "Acquisition request failed (HTTP 504).") throw error;
  if (message.includes("secret-symptom")) throw new Error("error echoed the body");
}

let timedOut = false;
try {
  await followAcquisition({
    request: (signal) =>
      new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      }),
    pause: async () => {},
    sliceMs: 5,
  });
} catch (error) {
  timedOut = (error as { message?: string }).message === "The acquisition request did not answer within 50 seconds.";
}
if (!timedOut) throw new Error("a hung slice should fail with a timeout");

const stage = jsonResponse(502, {
  detail: { kind: "Api", message: "Qualtrics response export failed at start (HTTP 400) [RTE_2]." },
});
try {
  await followAcquisition({
    request: async () => stage,
    pause: async () => {},
  });
  throw new Error("stage error should throw");
} catch (error) {
  const message = (error as { message?: string }).message ?? "";
  if (message !== "Qualtrics response export failed at start (HTTP 400) [RTE_2].") throw error;
}

try {
  await followAcquisition({
    request: async () => jsonResponse(202, { pending: true, stage: "elsewhere" }),
    pause: async () => {},
  });
  throw new Error("an unknown pending stage should not look like a report");
} catch (error) {
  const message = (error as { message?: string }).message ?? "";
  if (message !== "Qualtrics response export failed at poll.") throw error;
}

const token = await followAcquisition({
  request: async () =>
    jsonResponse(401, { detail: { kind: "Unauthorized", message: "Qualtrics rejected the API token." } }),
}).catch((error: { message?: string }) => error);
if (token.message !== "Qualtrics rejected the API token.") {
  throw new Error(token.message ?? "missing token message");
}

const stages: string[] = [];
let statusSlices = 0;
await followAcquisition({
  request: async () => {
    statusSlices += 1;
    if (statusSlices === 1) {
      return jsonResponse(202, {
        pending: true,
        stage: "start",
        status: "Loading contacts",
      });
    }
    if (statusSlices === 2) {
      return jsonResponse(202, {
        pending: true,
        stage: "start",
        status: "ada@example.com",
      });
    }
    return jsonResponse(200, { rows: [] });
  },
  pause: async () => {},
  onStatus: (status) => stages.push(status),
});
if (stages.length !== 1 || stages[0] !== "Loading contacts") {
  throw new Error(`status line should keep only the fixed phrase, got ${stages.join("|")}`);
}

const failed = await followAcquisition({
  request: async () =>
    jsonResponse(500, {
      detail: {
        kind: "Api",
        message: "Qualtrics response export failed at start (TypeError).",
        retryable: true,
      },
    }),
  pause: async () => {},
}).catch((error: { message?: string }) => error);
if (failed.message !== "Qualtrics response export failed at start (TypeError).") {
  throw new Error(failed.message ?? "missing stage error");
}
if (String(failed.message).includes("50 seconds")) {
  throw new Error("a returned 500 must not be replaced by the client timeout");
}

if (acquisitionStatus("Exporting survey 1 of 3") !== "Exporting survey 1 of 3") {
  throw new Error("survey progress should be shown");
}
if (acquisitionStatus("Exporting survey SV_1 of 3") !== null) {
  throw new Error("a survey id must not be shown");
}

const clientBudgetMs = (ACQUISITION_MAX_SLICES - 1) * ACQUISITION_PAUSE_MS;
if (clientBudgetMs < 12 * 60 * 1000) {
  throw new Error("the page gives up before a slow export can finish on the server");
}

const mine = acquisitionEventStatus(
  { status: "Loading contacts", attempt: "attempt-a" },
  "attempt-a",
);
const other = acquisitionEventStatus(
  { status: "Exporting survey 2 of 3", attempt: "attempt-b" },
  "attempt-a",
);
if (mine !== "Loading contacts" || other !== null) {
  throw new Error("a status event from another load must be ignored");
}

console.log("acquisition poll tests ok");
