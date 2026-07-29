<script lang="ts">
  import * as api from "../lib/api";
  import { app } from "../lib/state.svelte";
  import { errorMessage, type DistributionRow, type Method } from "../lib/types";
  import ConfirmDialog from "../components/ConfirmDialog.svelte";

  let method = $state<Method>("sms");
  let unsentOnly = $state(true);
  let rows = $state<DistributionRow[]>([]);
  let selected = $state<Set<string>>(new Set());
  let error = $state("");
  let notice = $state("");
  let loading = $state(false);
  let deleting = $state(false);
  let confirmDelete = $state(false);
  let progress = $state({ done: 0, total: 0 });

  $effect(() => {
    void app.selectedProjectId;
    void method;
    rows = [];
    selected = new Set();
    notice = "";
  });

  async function load() {
    if (!app.account || !app.project) return;
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
    if (!app.account || !app.project || selected.size === 0) return;
    deleting = true;
    error = "";
    notice = "";
    progress = { done: 0, total: selected.size };
    const unlisten = await api.onDeleteProgress((p) => (progress = p));
    try {
      const report = await api.deleteDistributions(
        app.account.id,
        app.project.id,
        method,
        [...selected],
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

  let visible = $derived(unsentOnly ? rows.filter((r) => r.unsent) : rows);

  function selectAllVisible() {
    selected =
      selected.size === visible.length
        ? new Set()
        : new Set(visible.map((r) => r.id));
  }
</script>

<h1>Distributions</h1>
<p class="subtitle">
  Invitations already booked with Qualtrics for
  <strong>{app.project?.name ?? ""}</strong>. Anything still in the future can be
  cancelled.
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
  <button onclick={load} disabled={loading}>{loading ? "Loading…" : "Load"}</button>
  <div class="checkbox" style="margin: 0;">
    <input id="dist-unsent" type="checkbox" bind:checked={unsentOnly} />
    <label for="dist-unsent">Not yet sent only</label>
  </div>
  <span class="spacer"></span>
  <button
    class="danger"
    onclick={() => (confirmDelete = true)}
    disabled={deleting || selected.size === 0}
  >
    Cancel selected ({selected.size})
  </button>
</div>

{#if deleting}
  <div class="card">
    <p>Cancelling {progress.done} of {progress.total}…</p>
    <progress value={progress.done} max={progress.total || 1}></progress>
  </div>
{/if}

{#if visible.length === 0 && !loading}
  <div class="empty">
    {rows.length === 0
      ? "Nothing loaded yet — press Load."
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
              checked={selected.size > 0 && selected.size === visible.length}
              onchange={selectAllVisible}
              aria-label="Select all shown"
            />
          </th>
          <th>Participant</th>
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
                aria-label={`Select invitation for ${row.contactName || row.id}`}
              />
            </td>
            <td>{row.contactName || "(unknown)"}</td>
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
  body={`${selected.size} invitation(s) will be withdrawn from Qualtrics. Any that have already been sent cannot be recalled.`}
  confirmLabel="Cancel invitations"
  danger
  onconfirm={remove}
/>
