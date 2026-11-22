import { createElapsed, createGroup, formatElapsed, formatElapsedSpoken } from "./busy.ts";

function clock(start = 0) {
  let at = start;
  return {
    now: () => at,
    set: (next: number) => {
      at = next;
    },
  };
}

const elapsed = formatElapsed(0);
if (elapsed !== "0:00") throw new Error(elapsed);
if (formatElapsed(59_000) !== "0:59") throw new Error("59s");
if (formatElapsed(60_000) !== "1:00") throw new Error("60s");
if (formatElapsed(754_000) !== "12:34") throw new Error("12:34");
if (formatElapsedSpoken(61_000) !== "1 minute 1 second") throw new Error("spoken");

const c = clock();
const timer = createElapsed(c);
timer.begin("load");
c.set(5_000);
if (timer.millis() !== 5_000) throw new Error("running");
timer.begin("load");
c.set(8_000);
if (timer.millis() !== 8_000) throw new Error("same operation must keep the original start");
timer.finish();
c.set(20_000);
if (timer.millis() !== 8_000) throw new Error("stopped time must freeze");
timer.begin("refresh");
c.set(23_000);
if (timer.millis() !== 3_000) throw new Error("a new operation starts again");

const groupClock = clock();
const group = createGroup(groupClock);
const first = group.retain("contacts");
const second = group.retain("contacts");
groupClock.set(4_000);
if (first.millis() !== 4_000 || second.millis() !== 4_000) {
  throw new Error("two indicators of one operation share a start");
}
const other = group.retain("schedule");
groupClock.set(7_000);
if (other.millis() !== 3_000) throw new Error("a different operation has its own start");
if (first.millis() !== 7_000) throw new Error("the first operation keeps running");
first.release();
groupClock.set(9_000);
if (second.millis() !== 9_000) throw new Error("one indicator leaving must not stop the other");
second.release();
const again = group.retain("contacts");
groupClock.set(12_000);
if (again.millis() !== 3_000) throw new Error("after the last indicator leaves, the next start is new");
again.release();

const separate = createGroup(groupClock);
const independent = separate.retain("contacts");
groupClock.set(15_000);
if (independent.millis() !== 3_000) throw new Error("groups do not share clocks");
independent.release();

console.log("busy timer tests ok");
