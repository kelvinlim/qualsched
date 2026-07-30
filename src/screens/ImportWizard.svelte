<script lang="ts">
  import { open } from "@tauri-apps/plugin-dialog";

  import * as api from "../lib/api";
  import { app } from "../lib/state.svelte";
  import { errorMessage, type ImportPreview } from "../lib/types";

  let yamlPath = $state("");
  let tokenPath = $state("");
  let tokenInput = $state("");
  let preview = $state<ImportPreview | null>(null);
  /** "" = create a new account; otherwise the id of the account to add the profile to. */
  let targetAccountId = $state("");
  let error = $state("");
  let busy = $state(false);
  let doneMessage = $state("");

  async function pickYaml() {
    const chosen = await open({
      multiple: false,
      filters: [{ name: "Config", extensions: ["yaml", "yml"] }],
    });
    if (typeof chosen === "string") {
      yamlPath = chosen;
      preview = null;
      doneMessage = "";
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
      const intoExisting = targetAccountId !== "";
      const accountId = intoExisting ? targetAccountId : preview.account.id;
      // The backend never regenerates it, so the id sent is the id to select.
      const projectId = preview.project.id;
      const projectName = preview.project.name;
      const accountName = intoExisting
        ? (targetAccount?.name ?? "")
        : preview.account.name;

      app.apply(
        await api.confirmLegacyImport({
          account: $state.snapshot(preview.account),
          project: $state.snapshot(preview.project),
          // Belt and braces: the backend returns before it reads either of these when a
          // target account is named, and that account's stored token must survive.
          token: intoExisting ? undefined : tokenInput.trim() || undefined,
          tokenPath: intoExisting ? undefined : tokenPath || undefined,
          targetAccountId: intoExisting ? targetAccountId : undefined,
        }),
      );
      // With the id omitted this would land on the account's *first* profile.
      app.select(accountId, projectId);
      doneMessage = intoExisting
        ? `Added "${projectName}" to "${accountName}". It is selected now — check the Survey profile screen before scheduling anything.`
        : `Imported "${accountName}". The new account is selected — check the Accounts and Survey profile screens before scheduling anything.`;
      preview = null;
      yamlPath = "";
      tokenPath = "";
      tokenInput = "";
      targetAccountId = "";
    } catch (e) {
      error = errorMessage(e);
    } finally {
      busy = false;
    }
  }

  let needsToken = $derived(
    !targetAccountId && preview !== null && !preview.tokenFound && !tokenInput.trim(),
  );

  let targetAccount = $derived(
    targetAccountId
      ? (app.config.accounts.find((a) => a.id === targetAccountId) ?? null)
      : null,
  );

  /**
   * Where the file disagrees with the account it is being added to. The account always
   * wins — these ids are scoped to one Qualtrics login, so a mismatch means the profile
   * points at something that is not there rather than failing loudly. Advisory only:
   * a stale account block in the file is a normal reason to import it anyway.
   */
  let conflicts = $derived.by(() => {
    const out: string[] = [];
    const target = targetAccount;
    if (!preview || !target) return out;
    const same = (a: string, b: string) =>
      a.trim().toLowerCase() === b.trim().toLowerCase();

    if (
      preview.account.dataCenter &&
      target.dataCenter &&
      !same(preview.account.dataCenter, target.dataCenter)
    ) {
      out.push(
        `The file was written for data center ${preview.account.dataCenter}, but "${target.name}" uses ${target.dataCenter}. Survey, mailing list and message IDs do not carry across data centers — this profile will almost certainly find nothing.`,
      );
    }
    if (!target.defaultDirectory) {
      out.push(
        `"${target.name}" has no contact directory set. Set one on the Accounts screen or the Contacts screen will find nobody.`,
      );
    } else if (
      preview.account.defaultDirectory &&
      !same(preview.account.defaultDirectory, target.defaultDirectory)
    ) {
      out.push(
        `The file's mailing list lives in directory ${preview.account.defaultDirectory}, but "${target.name}" uses ${target.defaultDirectory}. The account's own directory is what will be used.`,
      );
    }
    if (
      preview.account.libraryId &&
      target.libraryId &&
      !same(preview.account.libraryId, target.libraryId)
    ) {
      out.push(
        `The invitation templates in this file come from library ${preview.account.libraryId}; "${target.name}" uses ${target.libraryId}. Re-pick the templates on the Survey profile screen.`,
      );
    }

    // Only the pair is a real duplicate: one mailing list with two surveys is two
    // instruments on one cohort, and one survey with two lists is a multi-site study.
    const survey = preview.project.surveyId.trim();
    const list = preview.project.mailingListId.trim();
    const duplicate =
      survey && list
        ? target.projects.find(
            (p) => p.surveyId.trim() === survey && p.mailingListId.trim() === list,
          )
        : undefined;
    if (duplicate) {
      out.push(
        `"${target.name}" already has a profile ("${duplicate.name || "unnamed"}") on the same survey and mailing list. Importing adds a second one, and both would schedule the same people.`,
      );
    }
    return out;
  });
</script>

<h1>Import an existing config</h1>
<p class="subtitle">
  Reads a <span class="mono">config_qualtrics*.yaml</span> file from the command-line tool
  and turns it into a survey profile, either in a new account or in one you already have.
</p>

{#if error}<div class="banner error">{error}</div>{/if}
{#if doneMessage}
  <div class="banner ok">{doneMessage}</div>
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

    {#if app.config.accounts.length > 0}
      <div class="field">
        <label for="imp-target">Import into</label>
        <select id="imp-target" bind:value={targetAccountId}>
          <option value="">Create a new account</option>
          {#each app.config.accounts as account (account.id)}
            <option value={account.id}>
              Add to "{account.name || "(unnamed)"}" ({account.dataCenter ||
                "no data center"})
            </option>
          {/each}
        </select>
        <div class="hint">
          Adding to an existing account brings in the survey profile only. That account's
          API token, data center, contact directory and message library are left exactly as
          they are, and anything this file says about them is ignored.
        </div>
      </div>
    {/if}

    {#if conflicts.length > 0}
      <div class="banner warn">
        <strong>Check before importing:</strong>
        <ul>
          {#each conflicts as conflict, i (i)}<li>{conflict}</li>{/each}
        </ul>
      </div>
    {/if}

    <div class="grid2">
      {#if !targetAccountId}
        <div class="field">
          <label for="imp-name">Account name</label>
          <input id="imp-name" type="text" bind:value={preview.account.name} />
        </div>
        <div class="field">
          <label for="imp-dc">Data center</label>
          <input id="imp-dc" type="text" bind:value={preview.account.dataCenter} />
        </div>
      {/if}
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
        <!-- Account-level rows only when a new account is being made: showing them
             otherwise implies they will be applied to the account chosen above. -->
        {#if !targetAccountId}
          <tr><th>Directory</th><td class="mono">{preview.account.defaultDirectory || "—"}</td></tr>
          <tr><th>Library</th><td class="mono">{preview.account.libraryId || "—"}</td></tr>
        {/if}
        <tr><th>Survey</th><td class="mono">{preview.project.surveyId || "—"}</td></tr>
        <tr><th>Mailing list</th><td class="mono">{preview.project.mailingListId || "—"}</td></tr>
        <tr><th>SMS message</th><td class="mono">{preview.project.messageId || "—"}</td></tr>
        <tr><th>Email message</th><td class="mono">{preview.project.messageIdEmail || "—"}</td></tr>
        <tr><th>Time slots</th><td class="mono">{preview.project.embeddedDefaults.timeSlots}</td></tr>
        <tr><th>Contact method</th><td class="mono">{preview.project.embeddedDefaults.contactMethod}</td></tr>
        <tr><th>Expiry</th><td class="mono">{preview.project.minutesExpire} minutes</td></tr>
        {#if !targetAccountId}
          <tr>
            <th>TLS check</th>
            <td>{preview.account.verifyTls ? "on" : "off"}</td>
          </tr>
          <tr>
            <th>Token</th>
            <td>{preview.tokenFound ? "found in the token file" : "not found"}</td>
          </tr>
        {/if}
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

    {#if !preview.tokenFound && !targetAccountId}
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
