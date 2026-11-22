<script lang="ts">
  import { formatElapsed, formatElapsedSpoken } from "../lib/busy";

  let { operation, label }: { operation: string | number; label: string } = $props();
  let text = $state("0:00");
  let spoken = $state("0 minutes 0 seconds");

  $effect(() => {
    const op = operation;
    // Local start. A shared refcount finished the clock whenever one of the
    // two indicators cleaned up, which froze the other at 0:00.
    const startedAt = Date.now();
    void op;
    let bucket = -1;
    const paint = () => {
      const ms = Math.max(0, Date.now() - startedAt);
      text = formatElapsed(ms);
      const next = Math.floor(ms / 15_000);
      if (next !== bucket) {
        bucket = next;
        spoken = formatElapsedSpoken(ms);
      }
    };
    paint();
    const id = setInterval(paint, 250);
    return () => clearInterval(id);
  });
</script>

<span class="busy">
  <span class="busy-motion" aria-hidden="true"></span>
  <span class="sr-only" role="status">{label}, elapsed {spoken}</span>
  <span aria-hidden="true">{label}</span>
  <span class="busy-time" aria-hidden="true">{text}</span>
</span>
