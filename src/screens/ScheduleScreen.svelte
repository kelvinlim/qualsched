<script lang="ts">
  import * as api from "../lib/api";
  import { app } from "../lib/state.svelte";
  import {
    errorMessage,
    type SchedulePreview,
    type SendReport,
  } from "../lib/types";
  import ConfirmDialog from "../components/ConfirmDialog.svelte";

  let preview = $state<SchedulePreview | null>(null);
  let report = $state<SendReport | null>(null);
  let error = $state("");
  let computing = $state(false);
  let sending = $state(false);
  let confirmSend = $state(false);
  let progress = $state({ done: 0, total: 0 });

  // Clear any stale plan when the user switches profiles.
  $effect(() => {
    void app.selectedProjectId;
    preview = null;
    report = null;
    error = "";
  });

  async function compute() {
    if (!app.account || !app.project) return;
    computing = true;
    error = "";
    report = null;
    try {
      preview = await api.previewSchedule(app.account.id, app.project.id);
    } catch (e) {
      error = errorMessage(e);
      preview = null;
    } finally {
      computing = false;
    }
  }

  async function send() {
    if (!app.account || !app.project || !preview) return;
    sending = true;
    error = "";
    report = null;
    progress = { done: 0, total: preview.items.length };
    const unlisten = await api.onScheduleProgress((p) => {
      progress = { done: p.done, total: p.total };
    });
    try {
      report = await api.executeSchedule(
        app.account.id,
        app.project.id,
        $state.snapshot(preview),
      );
      // The plan is spent: SurveysScheduled now blocks these contacts.
      preview = null;
    } catch (e) {
      error = errorMessage(e);
    } finally {
      unlisten();
      sending = false;
    }
  }

  let contactCount = $derived(
    preview ? new Set(preview.items.map((i) => i.contactId)).size : 0,
  );
</script>

<h1>Schedule invitations</h1>
<p class="subtitle">
  Work out exactly which invitations would go out, review them, then send. Each
  invitation is booked with Qualtrics for a specific moment — nothing needs to stay
  running afterwards.
</p>

{#if error}<div class="banner error">{error}</div>{/if}

<div class="row" style="margin-bottom: 1rem;">
  <button class="primary" onclick={compute} disabled={computing || sending}>
    {computing ? "Working…" : "Compute plan"}
  </button>
  {#if preview && preview.items.length > 0}
    <button onclick={() => (confirmSend = true)} disabled={sending}>
      {sending ? "Sending…" : `Send ${preview.items.length} invitations`}
    </button>
  {/if}
</div>

{#if sending}
  <div class="card">
    <p>Scheduling {progress.done} of {progress.total}…</p>
    <progress value={progress.done} max={progress.total || 1}></progress>
  </div>
{/if}

{#if report}
  <div class="banner ok">
    Scheduled {report.scheduled} invitation(s).
    {#if report.failed.length === 0 && report.bookkeepingFailures.length === 0}
      Everything went through.
    {/if}
  </div>

  {#if report.failed.length > 0}
    <div class="card">
      <h2>{report.failed.length} invitation(s) failed</h2>
      <p class="hint">
        The rest still went out. Fix the cause and compute a fresh plan for what is left.
      </p>
      <div class="scroll-x">
        <table>
          <thead>
            <tr><th>Participant</th><th>Send time</th><th>Problem</th></tr>
          </thead>
          <tbody>
            {#each report.failed as failure, i (i)}
              <tr>
                <td>{failure.contactName}</td>
                <td class="mono">{failure.sendLocal}</td>
                <td class="wrap">{failure.error}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}

  {#if report.bookkeepingFailures.length > 0}
    <div class="banner warn">
      <strong>Needs attention.</strong> These participants received their invitations, but
      their record could not be updated to say so. Until you fix it by hand, a future run
      will schedule them a second time.
      <ul>
        {#each report.bookkeepingFailures as failure, i (i)}
          <li>{failure.contactName}: {failure.error}</li>
        {/each}
      </ul>
    </div>
  {/if}
{/if}

{#if preview}
  {#if preview.items.length === 0}
    <div class="empty">
      Nothing to schedule. Every participant was skipped — see the reasons below.
    </div>
  {:else}
    <div class="card">
      <h2>{preview.items.length} invitations for {contactCount} participant(s)</h2>
      <p class="hint">
        Times inside a random window were drawn now, so what you see here is exactly what
        will be sent.
      </p>
      <div class="scroll-x" style="max-height: 26rem; overflow-y: auto;">
        <table>
          <thead>
            <tr>
              <th>Participant</th>
              <th>Sent to</th>
              <th>Method</th>
              <th>Day</th>
              <th>Slot</th>
              <th>Survey</th>
              <th>Local time</th>
              <th>UTC</th>
              <th>Expires</th>
            </tr>
          </thead>
          <tbody>
            {#each preview.items as item, i (i)}
              <tr>
                <td>{item.contactName}</td>
                <td class="mono">{item.destination}</td>
                <td>{item.method}</td>
                <td>{item.dayIndex + 1}</td>
                <td class="mono">{item.slotLabel}</td>
                <td class="mono">{item.surveyLabel}</td>
                <td class="mono">{item.sendLocal}</td>
                <td class="mono">{item.sendUtc.replace("T", " ").slice(0, 16)}</td>
                <td class="mono">{item.expireUtc.replace("T", " ").slice(11, 16)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}

  {#if preview.skippedContacts.length > 0}
    <div class="card">
      <h2>{preview.skippedContacts.length} participant(s) skipped</h2>
      <div class="scroll-x">
        <table>
          <thead><tr><th>Participant</th><th>Reason</th></tr></thead>
          <tbody>
            {#each preview.skippedContacts as skip, i (i)}
              <tr>
                <td>{skip.contactName}</td>
                <td class="wrap">{skip.reason}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}

  {#if preview.skippedSlots.length > 0}
    <div class="card">
      <h2>{preview.skippedSlots.length} individual time(s) dropped</h2>
      <p class="hint">
        These moments have already passed, so an invitation booked for them would never
        arrive.
      </p>
      <div class="scroll-x" style="max-height: 14rem; overflow-y: auto;">
        <table>
          <thead><tr><th>Participant</th><th>Reason</th></tr></thead>
          <tbody>
            {#each preview.skippedSlots as skip, i (i)}
              <tr>
                <td>{skip.contactName}</td>
                <td class="wrap">{skip.reason}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}
{/if}

<ConfirmDialog
  bind:open={confirmSend}
  title="Send these invitations?"
  body={`${preview?.items.length ?? 0} invitations will be booked with Qualtrics for ${contactCount} participant(s). Sent invitations can be cancelled from the Distributions screen until their send time arrives.`}
  confirmLabel="Send"
  onconfirm={send}
/>
