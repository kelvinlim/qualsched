<script lang="ts">
  import { open } from "@tauri-apps/plugin-dialog";

  import * as api from "../lib/api";
  import { app } from "../lib/state.svelte";
  import { errorMessage, type ImportPreview } from "../lib/types";

  let yamlPath = $state("");
  let tokenPath = $state("");
  let tokenInput = $state("");
  let preview = $state<ImportPreview | null>(null);
  let error = $state("");
  let busy = $state(false);
  let done = $state(false);

  async function pickYaml() {
    const chosen = await open({
      multiple: false,
      filters: [{ name: "Config", extensions: ["yaml", "yml"] }],
    });
    if (typeof chosen === "string") {
      yamlPath = chosen;
      preview = null;
      done = false;
    }
  }

  async function pickToken() {
    const chosen = await open({ multiple: false });
    if (typeof chosen === "string") {
      tokenPath = chosen;
      preview = null;
    }
  }

  async function loadPreview() {
    if (!yamlPath) return;
    busy = true;
    error = "";
    try {
      preview = await api.previewLegacyImport(yamlPath, tokenPath || undefined);
    } catch (e) {
      error = errorMessage(e);
      preview = null;
    } finally {
      busy = false;
    }
  }

  async function confirm() {
    if (!preview) return;
    busy = true;
    error = "";
    try {
      const accountId = preview.account.id;
      app.apply(
        await api.confirmLegacyImport({
          account: $state.snapshot(preview.account),
          project: $state.snapshot(preview.project),
          token: tokenInput.trim() || undefined,
          tokenPath: tokenPath || undefined,
        }),
      );
      app.select(accountId);
      done = true;
      preview = null;
      yamlPath = "";
      tokenPath = "";
      tokenInput = "";
    } catch (e) {
      error = errorMessage(e);
    } finally {
      busy = false;
    }
  }

  let needsToken = $derived(preview !== null && !preview.tokenFound && !tokenInput.trim());
</script>

<h1>Import an existing config</h1>
<p class="subtitle">
  Reads a <span class="mono">config_qualtrics*.yaml</span> file from the command-line tool
  and turns it into an account with one survey profile.
</p>

{#if error}<div class="banner error">{error}</div>{/if}
{#if done}
  <div class="banner ok">
    Imported. The new account is selected — check the Accounts and Survey profile screens
    before scheduling anything.
  </div>
{/if}

<div class="card">
  <h2>1. Choose the files</h2>

  <div class="field">
    <label for="imp-yaml">Config file</label>
    <div class="row">
      <input id="imp-yaml" type="text" bind:value={yamlPath} placeholder="No file chosen" />
      <button onclick={pickYaml}>Browse…</button>
    </div>
  </div>

  <div class="field">
    <label for="imp-token">Token file (optional)</label>
    <div class="row">
      <input
        id="imp-token"
        type="text"
        bind:value={tokenPath}
        placeholder="The qualtrics_token file, if you have it"
      />
      <button onclick={pickToken}>Browse…</button>
    </div>
    <div class="hint">
      The API token is read from the <span class="mono">QUALTRICS_APITOKEN</span> line and
      stored in your system keychain. You can paste it by hand instead.
    </div>
  </div>

  <button class="primary" onclick={loadPreview} disabled={!yamlPath || busy}>
    {busy ? "Reading…" : "Read config"}
  </button>
</div>

{#if preview}
  <div class="card">
    <h2>2. Check what was found</h2>

    <div class="grid2">
      <div class="field">
        <label for="imp-name">Account name</label>
        <input id="imp-name" type="text" bind:value={preview.account.name} />
      </div>
      <div class="field">
        <label for="imp-dc">Data center</label>
        <input id="imp-dc" type="text" bind:value={preview.account.dataCenter} />
      </div>
      <div class="field">
        <label for="imp-proj">Profile name</label>
        <input id="imp-proj" type="text" bind:value={preview.project.name} />
      </div>
      <div class="field">
        <label for="imp-tz">Time zone</label>
        <input id="imp-tz" type="text" bind:value={preview.project.timezone} />
      </div>
    </div>

    <table style="margin-top: 0.5rem;">
      <tbody>
        <tr><th>Directory</th><td class="mono">{preview.account.defaultDirectory || "—"}</td></tr>
        <tr><th>Library</th><td class="mono">{preview.account.libraryId || "—"}</td></tr>
        <tr><th>Survey</th><td class="mono">{preview.project.surveyId || "—"}</td></tr>
        <tr><th>Mailing list</th><td class="mono">{preview.project.mailingListId || "—"}</td></tr>
        <tr><th>SMS message</th><td class="mono">{preview.project.messageId || "—"}</td></tr>
        <tr><th>Email message</th><td class="mono">{preview.project.messageIdEmail || "—"}</td></tr>
        <tr><th>Time slots</th><td class="mono">{preview.project.embeddedDefaults.timeSlots}</td></tr>
        <tr><th>Contact method</th><td class="mono">{preview.project.embeddedDefaults.contactMethod}</td></tr>
        <tr><th>Expiry</th><td class="mono">{preview.project.minutesExpire} minutes</td></tr>
        <tr>
          <th>TLS check</th>
          <td>{preview.account.verifyTls ? "on" : "off"}</td>
        </tr>
        <tr>
          <th>Token</th>
          <td>{preview.tokenFound ? "found in the token file" : "not found"}</td>
        </tr>
      </tbody>
    </table>

    {#if preview.warnings.length > 0}
      <div class="banner warn" style="margin-top: 0.85rem;">
        <strong>Worth knowing:</strong>
        <ul>
          {#each preview.warnings as warning, i (i)}
            <li>{warning}</li>
          {/each}
        </ul>
      </div>
    {/if}

    {#if !preview.tokenFound}
      <div class="field">
        <label for="imp-tok2">API token</label>
        <input
          id="imp-tok2"
          type="password"
          bind:value={tokenInput}
          placeholder="Paste the token, or add it later on the Accounts screen"
        />
      </div>
    {/if}

    <div class="row">
      <button class="primary" onclick={confirm} disabled={busy}>
        {busy ? "Importing…" : "Import"}
      </button>
      {#if needsToken}
        <span class="hint">
          Without a token the account is saved but cannot connect until you add one.
        </span>
      {/if}
    </div>
  </div>
{/if}
