<script lang="ts">
  import * as api from "@qualsched/api";
  import {
    dayGlyph,
    dayLabel,
    heatOf,
    rowWindow,
    statusPatchApplies,
    statusWriteIsCurrent,
    summaryText,
    visibleRows,
    windowSummary,
  } from "../lib/acquisition-view";
  import { app } from "../lib/state.svelte";
  import {
    errorMessage,
    type AcquisitionReport,
    type AcquisitionRow,
  } from "../lib/types";

  let report = $state<AcquisitionReport | null>(null);
  let error = $state("");
  let loading = $state(false);
  let activeOnly = $state(true);
  let span = $state<"7" | "study">("7");
  let marking = $state("");
  /** Bumped only when the account or profile changes, not when another row is toggled. */
  let contextGeneration = 0;
  /** Never reset, so a cleared map cannot hand ticket 1 to a new save. */
  let nextStatusTicket = 0;
  /** Latest in-flight save for each participant. A newer click on the same row wins. */
  const markTickets = new Map<string, number>();

  const shown = $derived(report ? visibleRows(report.rows, activeOnly) : []);

  $effect(() => {
    const accountId = app.selectedAccountId;
    const projectId = app.selectedProjectId;
    report = null;
    error = "";
    marking = "";
    markTickets.clear();
    contextGeneration += 1;
    if (accountId && projectId) void load(accountId, projectId);
    return () => {
      report = null;
    };
  });

  async function load(accountId = app.account?.id, projectId = app.project?.id) {
    if (!accountId || !projectId) return;
    loading = true;
    error = "";
    try {
      const next = await api.getAcquisition(accountId, projectId);
      if (app.selectedAccountId === accountId && app.selectedProjectId === projectId) {
        report = next;
      }
    } catch (e) {
      if (app.selectedAccountId === accountId && app.selectedProjectId === projectId) {
        report = null;
        error = errorMessage(e);
      }
    } finally {
      if (app.selectedAccountId === accountId && app.selectedProjectId === projectId) {
        loading = false;
      }
    }
  }

  async function setMonitor(row: AcquisitionRow, status: "active" | "inactive") {
    const accountId = app.account?.id;
    const projectId = app.project?.id;
    if (!accountId || !projectId || !report) return;
    const generation = contextGeneration;
    const ticket = ++nextStatusTicket;
    markTickets.set(row.contactId, ticket);
    marking = row.contactId;
    error = "";
    const stillCurrent = () =>
      statusWriteIsCurrent(
        generation,
        contextGeneration,
        ticket,
        markTickets.get(row.contactId) ?? 0,
      );
    try {
      const updated = await api.setAcquisitionStatus(
        accountId,
        projectId,
        row.contactId,
        status,
      );
      if (!stillCurrent()) return;
      if (
        !statusPatchApplies(
          app.selectedAccountId,
          app.selectedProjectId,
          accountId,
          projectId,
          report !== null,
        )
      ) {
        return;
      }
      report = {
        ...report,
        rows: report.rows.map((item) =>
          item.contactId === updated.contactId ? { ...item, monitor: updated.monitor } : item,
        ),
      };
    } catch (e) {
      if (
        stillCurrent() &&
        statusPatchApplies(
          app.selectedAccountId,
          app.selectedProjectId,
          accountId,
          projectId,
          true,
        )
      ) {
        error = errorMessage(e);
      }
    } finally {
      // Same check as a successful write. After a profile switch the map is cleared
      // and a new save may reuse nothing: this request must not delete that ticket.
      if (stillCurrent()) {
        markTickets.delete(row.contactId);
        if (marking === row.contactId) marking = "";
      }
    }
  }

  function zoneNote(row: AcquisitionRow): string {
    if (row.timezoneSource === "profile") return `${row.timezone} (survey profile default)`;
    if (row.timezoneSource === "invalid") return "timezone not readable";
    if (row.timezoneSource === "missing") return "no timezone";
    return row.timezone;
  }
</script>

<h1>Acquisition</h1>
<p class="subtitle">
  Each block is one local day. The number inside is completed surveys, and the count beside
  the row is completed/expected for the days on screen. Marking someone inactive only hides
  the row here. It does not cancel invitations, delete responses, or change who can be scheduled.
</p>

<div class="row" style="margin-bottom: 0.85rem;">
  <button class="primary" onclick={() => load()} disabled={loading || !app.hasProject}>
    {loading ? "Loading…" : "Refresh"}
  </button>
  <label>
    <input type="checkbox" bind:checked={activeOnly} />
    Active only
  </label>
  <div class="segmented" role="group" aria-label="Date range">
    <button class:active={span === "7"} aria-pressed={span === "7"} onclick={() => (span = "7")}>
      Last 7 days
    </button>
    <button
      class:active={span === "study"}
      aria-pressed={span === "study"}
      onclick={() => (span = "study")}
    >
      Entire study
    </button>
  </div>
</div>

{#if error}
  <div class="banner error">{error}</div>
{/if}

{#if report}
  <div class="banner">{report.prerequisite}</div>
  {#each report.limitations as note (note)}
    <p class="note">{note}</p>
  {/each}
  {#if !report.definitive}
    <p class="note">
      Counts that say "at least" omit responses that could not be matched safely.
      Excluded: {report.excluded.preview} preview, {report.excluded.test} test,
      {report.excluded.synthetic} synthetic, {report.excluded.spam} spam,
      {report.excluded.anonymous} without a recipient id,
      {report.excluded.unmatchedRecipient} for someone not on this list.
    </p>
  {/if}
{/if}

{#if loading && !report}
  <div class="empty">Loading completion counts…</div>
{:else if report && shown.length === 0}
  <div class="empty">
    {report.rows.length === 0 ? "No participants on this mailing list." : "No active participants. Turn off Active only to see everyone."}
  </div>
{:else if report}
  <div class="table-wrap">
    <table class="acquisition">
      <caption class="sr-only">
        Completed surveys against invitations still listed. Days use each participant's timezone.
      </caption>
      <thead>
        <tr>
          <th>Participant</th>
          <th>Status</th>
          <th>{span === "7" ? "Last 7 local days" : "Study days"}</th>
          <th>On screen</th>
          <th>To date</th>
        </tr>
      </thead>
      <tbody>
        {#each shown as row (row.contactId)}
          {@const days = rowWindow(row, span)}
          {@const window = windowSummary(days)}
          <tr>
            <td>
              <div>{row.displayName}</div>
              <div class="meta">{zoneNote(row)}</div>
            </td>
            <td>
              <button
                disabled={marking === row.contactId}
                onclick={() => setMonitor(row, row.monitor === "active" ? "inactive" : "active")}
              >
                {row.monitor === "active" ? "Active" : "Inactive"}
              </button>
            </td>
            <td>
              <div class="heats" class:study={span === "study"}>
                {#each days as day (day.date)}
                  <span
                    class="heat heat-{heatOf(day)}"
                    role="img"
                    aria-label={dayLabel(day)}
                    title={dayLabel(day)}
                  >
                    <span class="fill" aria-hidden="true"></span>
                    <span class="glyph">{dayGlyph(day)}</span>
                  </span>
                {/each}
              </div>
            </td>
            <td class="mono">{summaryText(window.completed, window.expected, !row.definitive)}</td>
            <td class="mono">
              {summaryText(row.toDate.completed, row.toDate.expected, row.toDate.provisional)}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}
