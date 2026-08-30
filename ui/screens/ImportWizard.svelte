<script lang="ts">
  import * as api from "@qualsched/api";
  import { app } from "../lib/state.svelte";
  import { errorMessage, type ImportPreview } from "../lib/types";

  let yamlName = $state("");
  let yamlText = $state("");
  let tokenName = $state("");
  let tokenText = $state("");
  let tokenInput = $state("");
  let preview = $state<ImportPreview | null>(null);
  /** "" = create a new account; otherwise the id of the account to add the profile to. */
  let targetAccountId = $state("");
  let error = $state("");
  let busy = $state(false);
  let doneMessage = $state("");

  async function readFile(file: File): Promise<string> {
    return await file.text();
  }

  async function onYaml(event: Event) {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    yamlName = file.name;
    yamlText = await readFile(file);
    preview = null;
    doneMessage = "";
  }

  async function onToken(event: Event) {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    tokenName = file.name;
    tokenText = await readFile(file);
    preview = null;
  }

  async function loadPreview() {
    if (!yamlText) return;
    busy = true;
    error = "";
    try {
      preview = await api.previewLegacyImport(yamlText, tokenText || undefined, yamlName);
      const selected = app.selectedAccountId;
      targetAccountId =
        selected && app.config.accounts.some((a) => a.id === selected) ? selected : "";
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
      const projectId = preview.project.id;
      const projectName = preview.project.name;
      const accountName = intoExisting
        ? (targetAccount?.name ?? "")
        : preview.account.name;

      const token =
        tokenInput.trim() ||
        tokenText
          .split("\n")
          .map((l) => l.trim())
          .filter((l) => l && !l.startsWith("#") && l.includes("="))
          .map((l) => {
            const [k, ...rest] = l.split("=");
            return k.trim() === "QUALTRICS_APITOKEN"
              ? rest.join("=").trim().replace(/^["']|["']$/g, "")
              : "";
          })
          .find(Boolean);

      app.apply(
        await api.confirmLegacyImport({
          account: $state.snapshot(preview.account),
          project: $state.snapshot(preview.project),
          token: intoExisting ? undefined : token || undefined,
          targetAccountId: intoExisting ? targetAccountId : undefined,
        }),
      );
      app.select(accountId, projectId);
      doneMessage = intoExisting
        ? `Added "${projectName}" to "${accountName}". It is selected now — check the Survey profile screen before scheduling anything.`
        : `Imported "${accountName}". The new account is selected — check the Accounts and Survey profile screens before scheduling anything.`;
      preview = null;
      yamlName = "";
      yamlText = "";
      tokenName = "";
      tokenText = "";
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
    <input id="imp-yaml" type="file" accept=".yaml,.yml,text/yaml" onchange={onYaml} />
    {#if yamlName}<div class="hint">{yamlName}</div>{/if}
  </div>

  <div class="field">
    <label for="imp-token">Token file (optional)</label>
    <input id="imp-token" type="file" onchange={onToken} />
    {#if tokenName}<div class="hint">{tokenName}</div>{/if}
    <div class="hint">
      The API token is read from the <span class="mono">QUALTRICS_APITOKEN</span> line and
      {api.platformCopy.importTokenHint} You can paste it by hand instead. Participant
      records in the YAML, if any, are ignored — they stay in Qualtrics.
    </div>
  </div>

  <button class="primary" onclick={loadPreview} disabled={!yamlText || busy}>
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
