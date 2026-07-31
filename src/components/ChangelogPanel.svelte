<script lang="ts" module>
  import { Marked } from "marked";
  import changelogSource from "../../CHANGELOG.md?raw";

  // Own instance rather than the `marked` singleton: GuideScreen configures that one
  // globally, so sharing it would make this rendering depend on module import order.
  const md = new Marked();

  // Parsed once when the module first loads, not on every open.
  const changelogHtml = md.parse(changelogSource, { async: false }) as string;
</script>

<script lang="ts">
  import { openUrl } from "@tauri-apps/plugin-opener";

  import { errorMessage, type UpdateInfo } from "../lib/types";

  let {
    open = $bindable(false),
    update = null,
    checking = false,
    checkError = "",
    oncheck,
  }: {
    open: boolean;
    update: UpdateInfo | null;
    checking: boolean;
    checkError: string;
    oncheck: () => void;
  } = $props();

  let openError = $state("");

  // The release body is markdown too, but it is fetched at runtime rather than
  // embedded, so it is parsed on demand.
  const notesHtml = $derived(
    update?.releaseNotes
      ? (md.parse(update.releaseNotes, { async: false }) as string)
      : "",
  );

  async function download() {
    if (!update) return;
    openError = "";
    try {
      await openUrl(update.releaseUrl);
    } catch (e) {
      openError = errorMessage(e);
    }
  }
</script>

<svelte:window
  onkeydown={(e) => {
    if (e.key === "Escape" && open) open = false;
  }}
/>

{#if open}
  <!-- The backdrop is a decorative click target; Escape and the panel's own close
       button are the keyboard paths, so it needs no role of its own. -->
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="backdrop" onclick={() => (open = false)}></div>

  <aside class="panel" aria-label="What's new">
    <header>
      <h2>What's new</h2>
      <button type="button" class="close" aria-label="Close" onclick={() => (open = false)}>
        ×
      </button>
    </header>

    <div class="body">
      <div class="update card">
        {#if update?.updateAvailable}
          <p class="headline">QualSched {update.latestVersion} is available.</p>
          <p class="note">You have {update.currentVersion}.</p>
          {#if notesHtml}
            <div class="guide notes">{@html notesHtml}</div>
          {/if}
          <button type="button" class="primary" onclick={download}>
            Download from GitHub
          </button>
        {:else if update}
          <p class="headline">You're on the latest version ({update.currentVersion}).</p>
        {:else}
          <p class="note">Update status unknown.</p>
        {/if}

        {#if openError}
          <div class="banner error">Could not open the browser: {openError}</div>
        {/if}
        {#if checkError}
          <div class="banner error">Could not check for updates: {checkError}</div>
        {/if}

        <button type="button" disabled={checking} onclick={oncheck}>
          {checking ? "Checking…" : "Check for updates"}
        </button>
      </div>

      <div class="guide">{@html changelogHtml}</div>
    </div>
  </aside>
{/if}

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    background: rgb(0 0 0 / 0.35);
    z-index: 20;
  }

  .panel {
    position: fixed;
    inset-block: 0;
    right: 0;
    z-index: 21;
    width: min(480px, 92vw);
    display: flex;
    flex-direction: column;
    background: var(--bg);
    border-left: 1px solid var(--border);
    box-shadow: -8px 0 24px rgb(0 0 0 / 0.18);
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    padding: 0.85rem 1rem;
    border-bottom: 1px solid var(--border);
    background: var(--panel);
  }

  header h2 {
    margin: 0;
    font-size: 1rem;
  }

  .close {
    font-size: 1.1rem;
    line-height: 1;
    padding: 0.15rem 0.5rem;
  }

  .body {
    overflow-y: auto;
    padding: 1rem;
  }

  .headline {
    margin: 0 0 0.25rem;
    font-weight: 600;
  }

  .note {
    margin: 0 0 0.75rem;
    color: var(--muted);
    font-size: 0.88rem;
  }

  .update button {
    margin-right: 0.5rem;
  }

  /* The release notes sit inside a card, so they should not carry the guide's
     full-page top margins. */
  .notes :global(:is(h1, h2, h3)) {
    margin-top: 0.75rem;
  }
</style>
