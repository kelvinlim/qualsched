<script lang="ts">
  import * as api from "../lib/api";
  import * as cache from "../lib/cache.svelte";
  import { app, newProject } from "../lib/state.svelte";
  import { errorMessage, type Project } from "../lib/types";
  import ApiDropdown from "../components/ApiDropdown.svelte";
  import ConfirmDialog from "../components/ConfirmDialog.svelte";

  let draft = $state<Project | null>(null);
  let error = $state("");
  let notice = $state("");
  let busy = $state(false);
  let confirmDelete = $state(false);
  let confirmCopies = $state(false);
  let copyProgress = $state<{ done: number; total: number } | null>(null);
  let messagePreview = $state("");

  $effect(() => {
    const project = app.project;
    draft = project ? $state.snapshot(project) : null;
    error = "";
    notice = "";
    messagePreview = "";
  });

  /**
   * Mirrors the Rust slot parser closely enough to give live feedback while typing.
   * The backend stays authoritative — this only catches obvious mistakes early.
   */
  function slotsProblem(raw: string): string {
    const text = raw.trim();
    if (!text) return "";
    const tokens = text.match(/\[[^\]]*\]|[^,]+/g) ?? [];
    for (const token of tokens) {
      const trimmed = token.trim();
      if (!trimmed) continue;
      const parts = trimmed.startsWith("[")
        ? trimmed.replace(/^\[|\]$/g, "").split(",")
        : [trimmed];
      if (trimmed.startsWith("[") && parts.length !== 2) {
        return `${trimmed} — a window needs exactly two times, like [800,900]`;
      }
      for (const part of parts) {
        const n = Number(part.trim());
        if (!Number.isInteger(n)) return `${part.trim()} — not a whole number like 800`;
        if (Math.floor(n / 100) > 23) return `${part.trim()} — hour above 23`;
        if (n % 100 > 59) return `${part.trim()} — minute above 59`;
      }
    }
    return "";
  }

  let slotsError = $derived(
    draft ? slotsProblem(draft.embeddedDefaults.timeSlots) : "",
  );

  function slotCount(raw: string): number {
    return (raw.trim().match(/\[[^\]]*\]|[^,]+/g) ?? []).filter((t) => t.trim()).length;
  }

  let slotsPerDay = $derived(draft ? slotCount(draft.embeddedDefaults.timeSlots) : 0);
  // Copies are created by their own command, so they live on the saved project rather
  // than the draft the form edits.
  let copies = $derived(app.project?.surveyCopies ?? []);
  let copiesNeeded = $derived(Math.max(0, slotsPerDay - 1));
  let copiesMissing = $derived(Math.max(0, copiesNeeded - copies.length));
  let copiesFromAnotherSurvey = $derived(
    !!app.project?.copiesSourceSurveyId &&
      !!draft?.surveyId &&
      app.project.copiesSourceSurveyId !== draft.surveyId,
  );

  async function makeCopies() {
    if (!draft || !app.account) return;
    busy = true;
    error = "";
    notice = "";
    copyProgress = { done: 0, total: copiesMissing };
    let unlisten: (() => void) | undefined;
    try {
      unlisten = await api.onSurveyCopyProgress((p) => (copyProgress = p));
      const accountId = app.account.id;
      const projectId = draft.id;
      const report = await api.createSurveyCopies(accountId, projectId);
      app.apply(report.config);
      app.select(accountId, projectId);
      // The survey list is cached for a few minutes; without this the new copies would
      // not show up in the Survey dropdown or the not-found check below.
      await cache.surveys(accountId, true);
      if (report.failed.length) {
        error = `${report.failed[0].name}: ${report.failed[0].error}`;
      }
      notice = report.created.length
        ? `Created ${report.created.length} ${report.created.length === 1 ? "copy" : "copies"}.`
        : "Nothing to create — this profile already has enough copies.";
    } catch (e) {
      error = errorMessage(e);
    } finally {
      unlisten?.();
      copyProgress = null;
      busy = false;
    }
  }

  async function saveThenCopy() {
    // The copy count comes from the saved time slots, so an unsaved edit would create a
    // different number than the confirmation just described.
    await save();
    if (!error) confirmCopies = true;
  }

  function addProject() {
    if (!app.account) return;
    const project = newProject();
    app.select(app.account.id, project.id);
    draft = project;
  }

  async function save() {
    if (!draft || !app.account) return;
    busy = true;
    error = "";
    notice = "";
    try {
      const accountId = app.account.id;
      const projectId = draft.id;
      app.apply(await api.saveProject(accountId, $state.snapshot(draft)));
      app.select(accountId, projectId);
      notice = "Saved.";
    } catch (e) {
      error = errorMessage(e);
    } finally {
      busy = false;
    }
  }

  async function removeProject() {
    if (!draft || !app.account) return;
    busy = true;
    try {
      app.apply(await api.deleteProject(app.account.id, draft.id));
    } catch (e) {
      error = errorMessage(e);
    } finally {
      busy = false;
    }
  }

  async function previewMessage(messageId: string) {
    if (!app.account || !messageId) return;
    error = "";
    try {
      messagePreview = await api.getMessageText(app.account.id, messageId);
    } catch (e) {
      error = errorMessage(e);
    }
  }
</script>

<h1>Survey profile</h1>
<p class="subtitle">
  A profile ties together one survey, one mailing list and the invitation templates used
  to reach it, plus the default scheduling values for new participants.
</p>

{#if !app.account}
  <div class="empty">Select an account first.</div>
{:else}
  <div class="row" style="align-items: flex-start; gap: 1.25rem;">
    <div style="width: 15rem; flex-shrink: 0;">
      {#each app.account.projects as project (project.id)}
        <button
          class="list-item"
          class:active={project.id === app.selectedProjectId}
          style="width: 100%; text-align: left;"
          onclick={() => app.select(app.account!.id, project.id)}
        >
          {project.name || "(unnamed)"}
        </button>
      {/each}
      <button style="width: 100%; margin-top: 0.35rem;" onclick={addProject}>
        + Add profile
      </button>
    </div>

    <div style="flex: 1; min-width: 0;">
      {#if !draft}
        <div class="empty">No survey profile yet. Add one to get started.</div>
      {:else}
        {#if error}<div class="banner error">{error}</div>{/if}
        {#if notice}<div class="banner ok">{notice}</div>{/if}

        <div class="card">
          <h2>Survey and recipients</h2>

          <div class="field">
            <label for="proj-name">Profile name</label>
            <input id="proj-name" type="text" bind:value={draft.name} />
          </div>

          <ApiDropdown
            label="Survey"
            bind:value={draft.surveyId}
            loader={async () =>
              (await cache.surveys(app.account!.id)).map((s) => ({
                id: s.id,
                label: `${s.name} (${s.id})`,
              }))}
          />

          <ApiDropdown
            label="Mailing list"
            bind:value={draft.mailingListId}
            hint={app.account.defaultDirectory
              ? ""
              : "Set the account's contact directory first."}
            loader={async () =>
              (await cache.mailingLists(app.account!.id, app.account!.defaultDirectory)).map(
                (m) => ({
                  id: m.id,
                  label: `${m.name}${m.contactCount === null ? "" : ` — ${m.contactCount} contacts`}`,
                }),
              )}
          />
        </div>

        <div class="card">
          <h2>Survey copies</h2>
          <p class="hint" style="margin-top: -0.4rem; margin-bottom: 0.85rem;">
            Qualtrics delivers only the first invitation for a survey to a participant
            each day. Each administration after the first therefore sends through a copy
            of the survey: the first slot of the day uses the survey above, the second
            uses <code>-c1</code>, and so on.
          </p>

          {#if copiesFromAnotherSurvey}
            <div class="banner warn">
              These copies were made from a different survey than the one selected above.
              Sending would mix the two — replace them by deleting the copies in Qualtrics
              and creating them again.
            </div>
          {/if}

          {#if copies.length}
            <table class="copies">
              <thead>
                <tr><th>Slot</th><th>Survey</th><th>ID</th></tr>
              </thead>
              <tbody>
                {#each copies as copy, i}
                  <tr>
                    <td>{i + 2}</td>
                    <td>{copy.name}</td>
                    <td class="mono">{copy.id}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {:else}
            <p class="hint">No copies yet.</p>
          {/if}

          {#if slotsPerDay > 1 && copiesMissing > 0}
            <div class="banner warn" style="margin-top: 0.85rem;">
              {slotsPerDay} slots a day need {copiesNeeded}
              {copiesNeeded === 1 ? "copy" : "copies"}; this profile has {copies.length}.
              Slots without a copy are skipped when you compute a plan.
            </div>
          {/if}

          {#if copyProgress}
            <div style="margin-top: 0.85rem;">
              <p>Creating {copyProgress.done} of {copyProgress.total}…</p>
              <progress value={copyProgress.done} max={copyProgress.total || 1}></progress>
            </div>
          {/if}

          <div class="row" style="margin-top: 0.85rem;">
            <button
              type="button"
              onclick={saveThenCopy}
              disabled={busy || !draft.surveyId || !!slotsError || copiesMissing === 0}
            >
              {busy && copyProgress
                ? "Creating…"
                : `Create ${copiesMissing} ${copiesMissing === 1 ? "copy" : "copies"}`}
            </button>
          </div>
        </div>

        <div class="card">
          <h2>Invitation templates</h2>

          <ApiDropdown
            label="SMS message"
            bind:value={draft.messageId}
            loader={async () =>
              (await cache.messages(app.account!.id)).map((m) => ({
                id: m.id,
                label: `${m.description} (${m.id})`,
              }))}
          />

          <ApiDropdown
            label="Email message"
            bind:value={draft.messageIdEmail}
            hint="Email needs its own template — an SMS template will not render as an email."
            loader={async () =>
              (await cache.messages(app.account!.id)).map((m) => ({
                id: m.id,
                label: `${m.description} (${m.id})`,
              }))}
          />

          <div class="row">
            <button
              type="button"
              onclick={() => previewMessage(draft!.messageId)}
              disabled={!draft.messageId}
            >
              Preview SMS text
            </button>
            <button
              type="button"
              onclick={() => previewMessage(draft!.messageIdEmail)}
              disabled={!draft.messageIdEmail}
            >
              Preview email text
            </button>
          </div>

          {#if messagePreview}
            <div class="field" style="margin-top: 0.85rem;">
              <label for="msg-preview">Message text</label>
              <textarea id="msg-preview" rows="5" readonly>{messagePreview}</textarea>
              <div class="hint">
                A short random tag is appended to each invitation before sending, so that
                two messages on the same day are not rejected as duplicates.
              </div>
            </div>
          {/if}
        </div>

        <div class="card">
          <h2>Email sender</h2>
          <p class="hint" style="margin-top: -0.4rem; margin-bottom: 0.85rem;">
            Used only for email invitations.
          </p>
          <div class="grid2">
            <div class="field">
              <label for="eh-from">From address</label>
              <input id="eh-from" type="text" bind:value={draft.emailHeader.fromEmail} />
            </div>
            <div class="field">
              <label for="eh-name">From name</label>
              <input id="eh-name" type="text" bind:value={draft.emailHeader.fromName} />
            </div>
            <div class="field">
              <label for="eh-reply">Reply-to address</label>
              <input id="eh-reply" type="text" bind:value={draft.emailHeader.replyToEmail} />
            </div>
            <div class="field">
              <label for="eh-subject">Subject</label>
              <input id="eh-subject" type="text" bind:value={draft.emailHeader.subject} />
            </div>
          </div>
        </div>

        <div class="card">
          <h2>Scheduling defaults</h2>
          <p class="hint" style="margin-top: -0.4rem; margin-bottom: 0.85rem;">
            Applied to participants who do not already have these values set. Existing
            per-participant values are never overwritten. Time zone and link expiry are
            also what the scheduler falls back to when a participant leaves them blank.
          </p>

          <div class="grid3">
            <div class="field">
              <label for="pd-tz">Time zone</label>
              <input id="pd-tz" type="text" bind:value={draft.timezone} placeholder="America/Chicago" />
              <div class="hint">An IANA name, like America/Chicago or Europe/London.</div>
            </div>
            <div class="field">
              <label for="pd-expire">Link expires after (minutes)</label>
              <input id="pd-expire" type="number" min="1" bind:value={draft.minutesExpire} />
            </div>
            <div class="field">
              <label for="pd-method">Contact method</label>
              <select id="pd-method" bind:value={draft.embeddedDefaults.contactMethod}>
                <option value="sms">SMS</option>
                <option value="email">Email</option>
              </select>
            </div>
          </div>

          <div class="grid3">
            <div class="field">
              <label for="pd-start">Start date</label>
              <input id="pd-start" type="date" bind:value={draft.embeddedDefaults.startDate} />
            </div>
            <div class="field">
              <label for="pd-days">Number of days</label>
              <input id="pd-days" type="number" min="0" bind:value={draft.embeddedDefaults.numDays} />
              <div class="hint">Must be above 0, or every participant is skipped.</div>
            </div>
          </div>

          <div class="field">
            <label for="pd-slots">Time slots</label>
            <input id="pd-slots" type="text" bind:value={draft.embeddedDefaults.timeSlots} />
            {#if slotsError}
              <div class="hint" style="color: var(--danger);">{slotsError}</div>
            {:else}
              <div class="hint">
                Times of day in 24-hour HHMM form, separated by commas: <span class="mono"
                  >800,1200,1600,2000</span
                >. Use a pair in brackets to send at a random moment inside a window:
                <span class="mono">[800,900]</span>.
              </div>
            {/if}
          </div>
        </div>

        <div class="row">
          <button class="primary" onclick={save} disabled={busy || !!slotsError}>Save</button>
          <span class="spacer"></span>
          <button class="danger" onclick={() => (confirmDelete = true)} disabled={busy}>
            Delete profile
          </button>
        </div>

        <ConfirmDialog
          bind:open={confirmDelete}
          title="Delete this survey profile?"
          body={`"${draft.name}" will be removed from QualSched. Nothing in Qualtrics is changed.`}
          confirmLabel="Delete"
          danger
          onconfirm={removeProject}
        />

        <ConfirmDialog
          bind:open={confirmCopies}
          title={`Create ${copiesMissing} survey ${copiesMissing === 1 ? "copy" : "copies"}?`}
          body={`This creates ${copiesMissing} real ${copiesMissing === 1 ? "survey" : "surveys"} in Qualtrics, named after the selected survey with -c suffixes. They are not removed when this profile is deleted, and responses collected through them live on each copy rather than the original.`}
          confirmLabel="Create"
          onconfirm={makeCopies}
        />
      {/if}
    </div>
  </div>
{/if}
