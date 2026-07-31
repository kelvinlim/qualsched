<script lang="ts">
  import { save } from "@tauri-apps/plugin-dialog";

  import * as api from "../lib/api";
  import { app } from "../lib/state.svelte";
  import { errorMessage } from "../lib/types";

  let busy = $state(false);
  let savedPath = $state("");
  let error = $state("");

  // Clearing the result when the profile changes stops a banner from claiming the
  // profile now on screen was the one just written.
  $effect(() => {
    void app.selectedProjectId;
    savedPath = "";
    error = "";
  });

  /** The `config_qualtrics` prefix is what an import reads a profile name from when a
   *  file predates the NAME field, so keep exports named the way imports expect. */
  function suggestedName(): string {
    const stem =
      (app.project?.name ?? "").trim().replace(/[^A-Za-z0-9._-]+/g, "_") || "profile";
    return `config_qualtrics_${stem}.yaml`;
  }

  async function exportConfig() {
    if (!app.account || !app.project) return;
    error = "";
    savedPath = "";
    const path = await save({
      defaultPath: suggestedName(),
      filters: [{ name: "Config", extensions: ["yaml", "yml"] }],
    });
    if (!path) return;
    busy = true;
    try {
      await api.exportProjectConfig(app.account.id, app.project.id, path);
      savedPath = path;
    } catch (e) {
      error = errorMessage(e);
    } finally {
      busy = false;
    }
  }

  let rows = $derived(
    app.account && app.project
      ? [
          ["Account", app.account.name || "(unnamed account)"],
          ["Data center", app.account.dataCenter],
          ["Contact directory", app.account.defaultDirectory],
          ["Message library", app.account.libraryId],
          ["Survey profile", app.project.name || "(unnamed profile)"],
          ["Survey", app.project.surveyId],
          ["Mailing list", app.project.mailingListId],
          ["SMS template", app.project.messageId],
          ["Email template", app.project.messageIdEmail],
          ["Time zone", app.project.timezone],
          ["Time slots", app.project.embeddedDefaults.timeSlots],
          ["Contact method", app.project.embeddedDefaults.contactMethod],
          ["Email sender", app.project.emailHeader.fromEmail],
        ]
      : [],
  );
</script>

<h1>Export Config</h1>
<p class="subtitle">
  Save <strong>{app.project?.name || "this survey profile"}</strong> as a settings file.
  Import Config on another computer reads it back, and so does the old command-line tool.
</p>

{#if error}<div class="banner error">Could not export: {error}</div>{/if}
{#if savedPath}<div class="banner ok">Saved to {savedPath}</div>{/if}

<div class="card">
  <h2>What goes in the file</h2>
  <div class="scroll-x">
    <table>
      <tbody>
        {#each rows as [label, value] (label)}
          <tr>
            <td>{label}</td>
            <td class="mono">{value || "—"}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  <p class="hint">
    Your API token is not written to this file. It stays in this computer's credential
    store, so whoever opens the file on another machine enters their own token. Per-
    participant schedules live in Qualtrics and are not part of it either.
  </p>
  <button class="primary" onclick={exportConfig} disabled={busy}>
    {busy ? "Saving…" : "Save as…"}
  </button>
</div>
