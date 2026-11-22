/** Elapsed time for one in-flight operation. The clock is injected so tests do not wait. */

export interface Clock {
  now(): number;
}

export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export function formatElapsedSpoken(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  const minuteWord = minutes === 1 ? "minute" : "minutes";
  const secondWord = seconds === 1 ? "second" : "seconds";
  return `${minutes} ${minuteWord} ${seconds} ${secondWord}`;
}

export function createElapsed(clock: Clock) {
  let origin: number | null = null;
  let stopped: number | null = null;
  let operation: string | number | null = null;
  return {
    begin(next: string | number) {
      if (operation === next && origin !== null && stopped === null) return;
      operation = next;
      origin = clock.now();
      stopped = null;
    },
    finish() {
      if (origin !== null && stopped === null) stopped = clock.now();
    },
    millis(at = clock.now()) {
      if (origin === null) return 0;
      return Math.max(0, (stopped ?? at) - origin);
    },
    running() {
      return origin !== null && stopped === null;
    },
  };
}

/** Several indicators for the same operation share one start time. */
export function createGroup(clock: Clock) {
  const timers = new Map<string | number, ReturnType<typeof createElapsed>>();
  const refs = new Map<string | number, number>();
  return {
    retain(operation: string | number) {
      const count = refs.get(operation) ?? 0;
      refs.set(operation, count + 1);
      let timer = timers.get(operation);
      if (!timer) {
        timer = createElapsed(clock);
        timer.begin(operation);
        timers.set(operation, timer);
      }
      return {
        millis: (at?: number) => timer.millis(at),
        release() {
          const left = (refs.get(operation) ?? 1) - 1;
          if (left <= 0) {
            timer.finish();
            refs.delete(operation);
            timers.delete(operation);
          } else {
            refs.set(operation, left);
          }
        },
      };
    },
  };
}

const live = createGroup({ now: () => Date.now() });

export function liveElapsed(operation: string | number) {
  return live.retain(operation);
}
