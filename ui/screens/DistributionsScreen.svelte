<script lang="ts">
  import * as api from "@qualsched/api";
  import { matchesQuery } from "../lib/filter";
  import { maskPhiText, participantLabel } from "../lib/phi";
  import { app } from "../lib/state.svelte";
  import { errorMessage, type DistributionRow, type Method } from "../lib/types";
  import BusyMark from "../components/BusyMark.svelte";
  import ConfirmDialog from "../components/ConfirmDialog.svelte";

  let method = $state<Method>("sms");
  let unsentOnly = $state(true);
  let query = $state("");
  let rows = $state<DistributionRow[]>([]);
  let selected = $state<Set<string>>(new Set());
  let error = $state("");
  let notice = $state("");
  let loading = $state(false);
  let loadOp = $state(0);
  let deleting = $state(false);
  let deleteOp = $state(0);
  let confirmDelete = $state(false);
  let progress = $state({ done: 0, total: 0 });

  $effect(() => {
    void app.selectedProjectId;
    void method;
    rows = [];
    selected = new Set();
    query = "";
    notice = "";
  });

  // Turning Hide PHI on clears any search text that could carry a participant's name/phone/email.
  $effect(() => {
    if (app.hidePhi) {
      query = "";
    }
  });

  async function load() {
    if (!app.account || !app.project) return;
    loadOp += 1;
    loading = true;
    error = "";
    try {
      rows = await api.listDistributions(app.account.id, app.project.id, method);
      selected = new Set();
    } catch (e) {
      error = errorMessage(e);
    } finally {
      loading = false;
    }
  }

  async function remove() {
    if (!app.account || !app.project || selectedRows.length === 0) return;
    deleteOp += 1;
    deleting = true;
    error = "";
    notice = "";
    progress = { done: 0, total: selectedRows.length };
    const unlisten = await api.onDeleteProgress((p) => (progress = p));
    try {
      // A copy's invitation can only be cancelled against the survey it was created
      // for, so each id travels with its own.
      const targets = selectedRows.map((r) => ({ id: r.id, surveyId: r.surveyId }));
      const report = await api.deleteDistributions(
        app.account.id,
        app.project.id,
        method,
        targets,
      );
      notice =
        report.failed.length === 0
          ? `Cancelled ${report.deleted} invitation(s).`
          : `Cancelled ${report.deleted}; ${report.failed.length} could not be cancelled (${report.failed[0].error}).`;
      await load();
    } catch (e) {
      error = errorMessage(e);
    } finally {
      unlisten();
      deleting = false;
    }
  }

  function toggle(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selected = next;
  }

  function rowLabel(row: DistributionRow): string {
    return participantLabel(
      app.hidePhi,
      row.contactName || "(unknown)",
      row.contactExtRef,
      row.contactId || row.contactLookupId || row.id,
    );
  }

  let listed = $derived(unsentOnly ? rows.filter((r) => r.unsent) : rows);
  let visible = $derived(
    listed.filter((r) =>
      app.hidePhi
        ? matchesQuery(query, [r.contactExtRef ?? "", r.contactId ?? "", r.contactLookupId, r.id])
        : matchesQuery(query, [r.contactName, r.contactPhone, r.contactEmail, r.contactExtRef ?? ""]),
    ),
  );

  /**
   * The selection survives a filter change, but nothing ever acts on a row the user
   * cannot see: every count, the confirmation text and the cancel itself go through this.
   * Cancelling is irreversible, so the number on the button has to be the number that
   * goes.
   */
  let selectedRows = $derived(visible.filter((r) => selected.has(r.id)));
  let hiddenSelected = $derived(selected.size - selectedRows.length);

  function selectAllVisible() {
    const next = new Set(selected);
    // A subset test, not a size comparison: two different sets can be the same size.
    if (visible.length > 0 && visible.every((r) => next.has(r.id))) {
      for (const row of visible) next.delete(row.id);
    } else {
      for (const row of visible) next.add(row.id);
    }
    selected = next;
  }
</script>

<h1>Distributions</h1>
<p class="subtitle">
  Invitations already booked with Qualtrics for this profile. Anything still in the future
  can be cancelled.
</p>

{#if error}<div class="banner error">{error}</div>{/if}
{#if notice}<div class="banner ok">{notice}</div>{/if}

<div class="row" style="margin-bottom: 0.85rem;">
  <div>
    <label for="dist-method" style="display: inline; margin-right: 0.4rem;">Type</label>
    <select id="dist-method" bind:value={method} style="width: auto;">
      <option value="sms">SMS</option>
      <option value="email">Email</option>
    </select>
  </div>
  <button onclick={load} disabled={loading}>
    {#if loading}
      <BusyMark operation={`distributions-${loadOp}`} label="Loading" />
    {:else}
      Load
    {/if}
  </button>
  <div class="checkbox" style="margin: 0;">
    <input id="dist-unsent" type="checkbox" bind:checked={unsentOnly} />
    <label for="dist-unsent">Not yet sent only</label>
  </div>
  <input
    class="search"
    type="search"
    bind:value={query}
    placeholder={app.hidePhi ? "Search external reference or ID" : "Search name, phone or email"}
    aria-label="Search invitations"
  />
  {#if query.trim()}
    <span class="hint" style="margin: 0;">{visible.length} of {listed.length} shown</span>
  {/if}
  {#if hiddenSelected > 0}
    <span class="hint" style="margin: 0;">
      {hiddenSelected} selected but hidden
      <button class="link" onclick={() => (selected = new Set())}>clear</button>
    </span>
  {/if}
  <span class="spacer"></span>
  <button
    class="danger"
    onclick={() => (confirmDelete = true)}
    disabled={deleting || selectedRows.length === 0}
  >
    Cancel selected ({selectedRows.length})
  </button>
</div>

{#if deleting}
  <div class="card">
    <p>
      <BusyMark operation={`distributions-delete-${deleteOp}`} label="Cancelling" />
      {progress.done} of {progress.total}
    </p>
    <progress value={progress.done} max={progress.total || 1}></progress>
  </div>
{/if}

{#if visible.length === 0 && !loading}
  <div class="empty">
    {rows.length === 0
      ? "Nothing loaded yet — press Load."
      : query.trim()
        ? "No invitations match this search."
        : "No invitations match this filter."}
  </div>
{:else}
  <div class="card scroll-x" style="padding: 0;">
    <table>
      <thead>
        <tr>
          <th>
            <input
              type="checkbox"
              checked={visible.length > 0 && selectedRows.length === visible.length}
              onchange={selectAllVisible}
              aria-label="Select all shown"
            />
          </th>
          <th>Participant</th>
          <th>Phone</th>
          <th>Email</th>
          <th>Survey</th>
          <th>Send time (local)</th>
          <th>Send time (UTC)</th>
          <th>Status</th>
          <th>ID</th>
        </tr>
      </thead>
      <tbody>
        {#each visible as row (row.id)}
          <tr>
            <td>
              <input
                type="checkbox"
                checked={selected.has(row.id)}
                onchange={() => toggle(row.id)}
                aria-label={`Select invitation for ${rowLabel(row)}`}
              />
            </td>
            <td class:mono={app.hidePhi}>{rowLabel(row)}</td>
            <td class="mono">{maskPhiText(app.hidePhi, row.contactPhone)}</td>
            <td class="mono">{maskPhiText(app.hidePhi, row.contactEmail)}</td>
            <td class="mono">{row.surveyLabel}</td>
            <td class="mono">{row.sendLocal || "—"}</td>
            <td class="mono">{row.sendDate.replace("T", " ").replace("Z", "")}</td>
            <td>
              {#if row.unsent}
                <span class="badge warn">scheduled</span>
              {:else}
                <span class="badge muted">sent</span>
              {/if}
            </td>
            <td class="mono">{row.id}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}

<ConfirmDialog
  bind:open={confirmDelete}
  title="Cancel these invitations?"
  body={`${selectedRows.length} invitation(s) will be withdrawn from Qualtrics. Any that have already been sent cannot be recalled.`}
  confirmLabel="Cancel invitations"
  danger
  onconfirm={remove}
/>
