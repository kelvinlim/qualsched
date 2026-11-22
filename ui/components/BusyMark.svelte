<script lang="ts">
  import { formatElapsed, formatElapsedSpoken, liveElapsed } from "../lib/busy";

  let { operation, label }: { operation: string | number; label: string } = $props();
  let text = $state("0:00");
  let spoken = $state("0 minutes 0 seconds");

  $effect(() => {
    const op = operation;
    const handle = liveElapsed(op);
    let bucket = -1;
    const paint = () => {
      const ms = handle.millis();
      text = formatElapsed(ms);
      const next = Math.floor(ms / 15_000);
      if (next !== bucket) {
        bucket = next;
        spoken = formatElapsedSpoken(ms);
      }
    };
    paint();
    const id = setInterval(paint, 250);
    return () => {
      clearInterval(id);
      handle.release();
    };
  });
</script>

<span class="busy">
  <span class="busy-motion" aria-hidden="true"></span>
  <span class="sr-only" role="status">{label}, elapsed {spoken}</span>
  <span aria-hidden="true">{label}</span>
  <span class="busy-time" aria-hidden="true">{text}</span>
</span>
