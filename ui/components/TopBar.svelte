<script lang="ts">
  import { app } from "../lib/state.svelte";
</script>

<div class="topbar">
  <nav class="breadcrumb" aria-label="Breadcrumb">
    {#if app.account}
      <button class="link" onclick={() => app.go("accounts")}>
        {app.account.name || "(unnamed account)"}
      </button>
      {#if app.account.dataCenter}
        <span class="badge muted">{app.account.dataCenter}</span>
      {/if}
      <span class="sep" aria-hidden="true">/</span>
      <button class="link" onclick={() => app.go("project")}>
        {app.project
          ? app.project.name || "(unnamed profile)"
          : "Choose a survey profile"}
      </button>
    {:else}
      <button class="link" onclick={() => app.go("accounts")}>Choose an account</button>
    {/if}
  </nav>

  <label
    class="phi-toggle"
    class:active={app.hidePhi}
    title="Show external reference or contact ID instead of participant names, and mask phone numbers and email addresses"
  >
    <input
      type="checkbox"
      checked={app.hidePhi}
      onchange={(e) => app.setHidePhi(e.currentTarget.checked)}
    />
    Hide PHI
  </label>
</div>
