<script lang="ts">
  import * as api from "@qualsched/api";
  import * as cache from "../lib/cache.svelte";
  import {
    ALL_CONTAINERS,
    effectiveMessageLibrary,
    formatMailingListLabel,
    formatMessageLabel,
    type PickerItem,
  } from "../lib/container-resolve";
  import { withAddedProject } from "../lib/project";
  import { app, newProject } from "../lib/state.svelte";
  import { errorMessage, type Method, type Project } from "../lib/types";
  import ApiDropdown from "../components/ApiDropdown.svelte";
  import BusyMark from "../components/BusyMark.svelte";
  import ConfirmDialog from "../components/ConfirmDialog.svelte";
  import ContainerPicker from "../components/ContainerPicker.svelte";

  let draft = $state<Project | null>(null);
  let error = $state("");
  let notice = $state("");
  let busy = $state(false);
  let busyOp = $state(0);
  let confirmDelete = $state(false);
  let confirmForgetCopies = $state(false);
  let messagePreview = $state("");

  $effect(() => {
    const account = app.account;
    if (account && account.projects.length > 0 && !app.project) {
      app.select(account.id, account.projects[0].id);
    }
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

  // Clones left over from 0.1.4. Nothing creates them any more; they live on the saved
  // project rather than the draft the form edits, and the card below is the only way out.
  let copies = $derived(app.project?.surveyCopies ?? []);

  async function forgetCopies() {
    if (!draft || !app.account) return;
    busyOp += 1;
    busy = true;
    error = "";
    notice = "";
    try {
      const accountId = app.account.id;
      const projectId = draft.id;
      app.apply(await api.forgetSurveyCopies(accountId, projectId));
      app.select(accountId, projectId);
      notice = "Forgot the leftover copies.";
    } catch (e) {
      error = errorMessage(e);
    } finally {
      busy = false;
    }
  }

  function addProject() {
    if (!app.account) return;
    const project = newProject();
    const accountId = app.account.id;
    app.apply(withAddedProject(app.config, accountId, project));
    app.select(accountId, project.id);
  }

  async function save() {
    if (!draft || !app.account) return;
    busyOp += 1;
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
    busyOp += 1;
    busy = true;
    try {
      app.apply(await api.deleteProject(app.account.id, draft.id));
    } catch (e) {
      error = errorMessage(e);
    } finally {
      busy = false;
    }
  }

  async function loadDirectoryLists(
    accountId: string,
    directoryId: string,
    force: boolean,
  ): Promise<PickerItem[]> {
    const showContainer = directoryId === ALL_CONTAINERS;
    const lists = await cache.mailingLists(accountId, directoryId, force);
    return lists.map((m) => ({
      id: m.id,
      label: formatMailingListLabel(m, showContainer),
      name: m.name,
      containerId: m.directoryId || (showContainer ? "" : directoryId),
      containerName: m.directoryName || "",
    }));
  }

  async function loadLibraryMessages(
    accountId: string,
    libraryId: string,
    force: boolean,
  ): Promise<PickerItem[]> {
    const showContainer = libraryId === ALL_CONTAINERS;
    const msgs = await cache.messages(accountId, libraryId, force);
    return msgs.map((m) => ({
      id: m.id,
      label: formatMessageLabel(m, showContainer),
      name: m.description,
      containerId: m.libraryId || (showContainer ? "" : libraryId),
      containerName: m.libraryName || "",
      category: m.category,
    }));
  }

  async function previewMessage(messageId: string, method: Method) {
    if (!app.account || !draft || !messageId) return;
    error = "";
    try {
      const libraryId = effectiveMessageLibrary(app.account, draft, method);
      messagePreview = await api.getMessageText(
        app.account.id,
        messageId,
        libraryId || undefined,
      );
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
        {#if app.account.projects.length === 0}
          <div class="empty">Choose a profile from the list, or add one</div>
        {/if}
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
                name: s.name,
              }))}
          />

          {#key `${app.account.id}:${draft.id}`}
            <ContainerPicker
              label="Mailing list"
              containerLabel="Directory"
              allLabel="All directories"
              bind:value={draft.mailingListId}
              bind:containerOverride={draft.directoryId}
              defaultContainerId={app.account.defaultDirectory}
              hint={app.account.defaultDirectory || draft.directoryId
                ? ""
                : "No account contact directory set — search all directories to pick a list."}
              loadContainers={(force) => cache.directories(app.account!.id, force)}
              loadItems={(dirId, force) =>
                loadDirectoryLists(app.account!.id, dirId, force)}
            />
          {/key}
        </div>

        {#if copies.length}
          <div class="card">
            <h2>Leftover survey copies</h2>
            <p class="hint" style="margin-top: -0.4rem; margin-bottom: 0.85rem;">
              An earlier version copied this profile's survey to work around Qualtrics
              delivering only one invitation a day. That did not work, and QualSched no
              longer sends through these. They are listed so any invitation still scheduled
              against them stays cancellable on the Distributions screen.
            </p>

            <table>
              <thead>
                <tr><th>Survey</th><th>ID</th></tr>
              </thead>
              <tbody>
                {#each copies as copy (copy.id)}
                  <tr>
                    <td>{copy.name}</td>
                    <td class="mono">{copy.id}</td>
                  </tr>
                {/each}
              </tbody>
            </table>

            <div class="row" style="margin-top: 0.85rem;">
              <button type="button" onclick={() => (confirmForgetCopies = true)} disabled={busy}>
                Forget these copies
              </button>
            </div>
          </div>
        {/if}

        <div class="card">
          <h2>Invitation templates</h2>

          {#key `${app.account.id}:${draft.id}`}
            <ContainerPicker
              label="SMS message"
              containerLabel="Library"
              allLabel="All libraries"
              bind:value={draft.messageId}
              bind:containerOverride={draft.messageLibraryId}
              defaultContainerId={app.account.libraryId}
              loadContainers={(force) => cache.libraries(app.account!.id, force)}
              loadItems={(libId, force) =>
                loadLibraryMessages(app.account!.id, libId, force)}
            />

            <ContainerPicker
              label="Email message"
              containerLabel="Library"
              allLabel="All libraries"
              bind:value={draft.messageIdEmail}
              bind:containerOverride={draft.messageEmailLibraryId}
              defaultContainerId={app.account.libraryId}
              hint="Email needs its own template — an SMS template will not render as an email."
              loadContainers={(force) => cache.libraries(app.account!.id, force)}
              loadItems={(libId, force) =>
                loadLibraryMessages(app.account!.id, libId, force)}
            />
          {/key}

          <div class="row">
            <button
              type="button"
              onclick={() => previewMessage(draft!.messageId, "sms")}
              disabled={!draft.messageId}
            >
              Preview SMS text
            </button>
            <button
              type="button"
              onclick={() => previewMessage(draft!.messageIdEmail, "email")}
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
                A short random tag is added to each invitation before sending, so that
                two messages on the same day are not rejected as duplicates. For SMS it
                is placed before the survey-link piped text.
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
          {#if busy}
            <BusyMark operation={`project-${busyOp}`} label="Working" />
          {/if}
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
          bind:open={confirmForgetCopies}
          title="Forget these copies?"
          body="The surveys stay in your Qualtrics account — this only stops QualSched checking them. Cancel anything still scheduled against them on the Distributions screen first: once forgotten, those invitations can no longer be withdrawn from here."
          confirmLabel="Forget"
          danger
          onconfirm={forgetCopies}
        />
      {/if}
    </div>
  </div>
{/if}
