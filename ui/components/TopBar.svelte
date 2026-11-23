<script lang="ts">
  import { maskPhiText } from "../lib/phi";
  import { app } from "../lib/state.svelte";
</script>

<div class="topbar">
  <nav class="breadcrumb" aria-label="Breadcrumb">
    {#if app.account}
      <button
        class="link"
        aria-label={app.hidePhi ? "Account (hidden)" : undefined}
        onclick={() => app.go("accounts")}
      >
        {maskPhiText(app.hidePhi, app.account.name || "(unnamed account)")}
      </button>
      {#if app.account.dataCenter}
        <span class="badge muted">{app.account.dataCenter}</span>
      {/if}
      <span class="sep" aria-hidden="true">/</span>
      <button
        class="link"
        aria-label={app.hidePhi && app.project ? "Survey profile (hidden)" : undefined}
        onclick={() => app.go("project")}
      >
        {app.project
          ? maskPhiText(app.hidePhi, app.project.name || "(unnamed profile)")
          : "Choose a survey profile"}
      </button>
    {:else}
      <button class="link" onclick={() => app.go("accounts")}>Choose an account</button>
    {/if}
  </nav>

  <label
    class="phi-toggle"
    class:active={app.hidePhi}
    title="Show external reference or contact ID instead of participant names, and mask phone numbers, email addresses, and account/study names"
  >
    <input
      type="checkbox"
      checked={app.hidePhi}
      onchange={(e) => app.setHidePhi(e.currentTarget.checked)}
    />
    Hide PHI
  </label>
</div>
