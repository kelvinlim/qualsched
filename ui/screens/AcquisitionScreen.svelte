<script lang="ts">
  import { untrack } from "svelte";
  import * as api from "@qualsched/api";
  import {
    WEEKDAY_HEADERS,
    dayDetail,
    dayGlyph,
    dayLabel,
    groupByWeeks,
    heatOf,
    promptStatusLabel,
    rowSearchFields,
    rowWindow,
    statusPatchApplies,
    statusWriteIsCurrent,
    summaryText,
    visibleRows,
    windowSummary,
  } from "../lib/acquisition-view";
  import { matchesQuery } from "../lib/filter";
  import { app } from "../lib/state.svelte";
  import { participantLabel } from "../lib/phi";
  import BusyMark from "../components/BusyMark.svelte";
  import { acquisitionStatus } from "../lib/acquisition-poll";
  import {
    errorMessage,
    type AcquisitionDay,
    type AcquisitionReport,
    type AcquisitionRow,
  } from "../lib/types";

  let report = $state<AcquisitionReport | null>(null);
  let error = $state("");
  let stageLine = $state("");
  let loading = $state(false);
  let loadOp = $state(0);
  let loadController: AbortController | null = null;
  let activeOnly = $state(true);
  let query = $state("");
  let span = $state<"7" | "study">("7");
  let marking = $state("");
  let hovered = $state<{
    day: AcquisitionDay;
    left: number;
    top: number;
    below: boolean;
  } | null>(null);
  /** Bumped only when the account or profile changes, not when another row is toggled. */
  let contextGeneration = 0;
  /** Never reset, so a cleared map cannot hand ticket 1 to a new save. */
  let nextStatusTicket = 0;
  /** Latest in-flight save for each participant. A newer click on the same row wins. */
  const markTickets = new Map<string, number>();

  const activeRows = $derived(report ? visibleRows(report.rows, activeOnly) : []);
  const shown = $derived(
    activeRows.filter((row) => matchesQuery(query, rowSearchFields(row, app.hidePhi))),
  );
  const hoveredDetail = $derived(hovered ? dayDetail(hovered.day) : null);

  $effect(() => {
    void app.selectedAccountId;
    void app.selectedProjectId;
    // Never start downloading on open or profile switch; the researcher clicks Load.
    untrack(() => {
      loadController?.abort();
      loadController = null;
      loading = false;
      report = null;
      error = "";
      stageLine = "";
      hovered = null;
      marking = "";
      query = "";
      markTickets.clear();
      contextGeneration += 1;
    });
    return () => {
      report = null;
      hovered = null;
      loadController?.abort();
    };
  });

  // Turning Hide PHI on clears any search text that could carry a participant's name, phone, or email.
  $effect(() => {
    if (app.hidePhi) {
      query = "";
    }
  });

  $effect(() => {
    const clear = () => {
      hovered = null;
    };
    window.addEventListener("scroll", clear, true);
    window.addEventListener("resize", clear);
    return () => {
      window.removeEventListener("scroll", clear, true);
      window.removeEventListener("resize", clear);
    };
  });

  async function load(accountId = app.account?.id, projectId = app.project?.id) {
    if (!accountId || !projectId) return;
    loadController?.abort();
    const controller = new AbortController();
    loadController = controller;
    loadOp += 1;
    loading = true;
    error = "";
    stageLine = "";
    hovered = null;
    try {
      const next = await api.getAcquisition(
        accountId,
        projectId,
        controller.signal,
        (status) => {
          if (controller.signal.aborted) return;
          const safe = acquisitionStatus(status);
          if (
            safe &&
            app.selectedAccountId === accountId &&
            app.selectedProjectId === projectId
          ) {
            stageLine = safe;
          }
        },
      );
      if (controller.signal.aborted) return;
      if (app.selectedAccountId === accountId && app.selectedProjectId === projectId) {
        report = next;
      }
    } catch (e) {
      if (controller.signal.aborted) return;
      if (app.selectedAccountId === accountId && app.selectedProjectId === projectId) {
        report = null;
        error = errorMessage(e);
      }
    } finally {
      if (
        loadController === controller &&
        app.selectedAccountId === accountId &&
        app.selectedProjectId === projectId
      ) {
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

  function openDayHover(event: MouseEvent | FocusEvent, day: AcquisitionDay) {
    const target = event.currentTarget;
    if (!(target instanceof HTMLElement)) return;
    const rect = target.getBoundingClientRect();
    const width = 260;
    const margin = 12;
    const vw = typeof window !== "undefined" ? window.innerWidth : 1024;
    const left = Math.min(
      Math.max(rect.left + rect.width / 2, width / 2 + margin),
      vw - width / 2 - margin,
    );
    const below = rect.top < 190;
    const top = below ? rect.bottom + 8 : rect.top - 8;
    hovered = { day, left, top, below };
  }

  function closeDayHover(day: AcquisitionDay) {
    if (hovered?.day === day) hovered = null;
  }

  function zoneNote(row: AcquisitionRow): string {
    if (row.timezoneSource === "profile") return `${row.timezone} (survey profile default)`;
    if (row.timezoneSource === "invalid") return "timezone not readable";
    if (row.timezoneSource === "missing") return "no timezone";
    return row.timezone;
  }

  function hasNonZeroExclusions(rep: AcquisitionReport): boolean {
    const ex = rep.excluded;
    return (
      ex.preview +
        ex.test +
        ex.synthetic +
        ex.spam +
        ex.unfinished +
        ex.otherStatus +
        ex.anonymous +
        ex.unmatchedRecipient +
        ex.conflict +
        ex.duplicateIds +
        ex.unjoinedInvitations >
      0
    );
  }
</script>

<h1>Acquisition</h1>
<p class="subtitle">
  Each box is one local day, arranged Monday–Sunday and stacked week over week so weekday
  and weekend patterns align vertically. Hover or focus a box for send times and statuses.
  Marking someone inactive only hides the row here.
</p>

<div class="row" style="margin-bottom: 0.85rem;">
  <button class="primary" onclick={() => load()} disabled={loading || !app.hasProject}>
    {#if loading}
      <BusyMark operation={`acquisition-${loadOp}`} label="Loading" />
    {:else if report}
      Refresh
    {:else}
      Load
    {/if}
  </button>
  <label
    title="Show participants not marked Inactive who have survey invitations during the current Monday–Sunday week"
  >
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
  <input
    class="search"
    type="search"
    bind:value={query}
    placeholder={app.hidePhi
      ? "Search external reference or ID"
      : "Search name, reference, phone or email"}
    aria-label="Search participants"
  />
  {#if report && query.trim()}
    <span class="hint" style="margin: 0;">{shown.length} of {activeRows.length} shown</span>
  {/if}
</div>

{#if loading && stageLine}
  <p class="meta" aria-live="polite">{stageLine}</p>
{/if}

{#if error}
  <div class="banner error">{error}</div>
{/if}

{#if report}
  <div class="banner">{report.prerequisite}</div>
  {#each report.limitations as note (note)}
    <p class="note">{note}</p>
  {/each}
  {#if !report.definitive && hasNonZeroExclusions(report)}
    <p class="note">
      Counts that say "at least" omit items that could not be matched safely.
      Unjoined invitations: {report.excluded.unjoinedInvitations}.
    </p>
  {/if}
{/if}

{#if loading && !report}
  <div class="empty">
    <BusyMark operation={`acquisition-${loadOp}`} label="Loading completion counts" />
  </div>
{:else if !report && !error}
  <div class="empty">Nothing loaded yet — press Load.</div>
{:else if report && shown.length === 0}
  <div class="empty">
    {#if report.rows.length === 0}
      No participants on this mailing list.
    {:else if activeRows.length === 0}
      No active participants with survey invitations this week. Turn off Active only to see everyone.
    {:else}
      No participants match this search.
    {/if}
  </div>
{:else if report}
  <div class="heat-legend" aria-label="Day box legend">
    <span class="heat-legend-item">
      <span class="heat heat-swatch heat-4" aria-hidden="true">
        <span class="fill"></span>
        <span class="glyph">4</span>
      </span>
      All complete (100%)
    </span>
    <span class="heat-legend-item">
      <span class="heat heat-swatch heat-2" aria-hidden="true">
        <span class="fill"></span>
        <span class="glyph">2</span>
      </span>
      Partial
    </span>
    <span class="heat-legend-item">
      <span class="heat heat-swatch heat-0" aria-hidden="true">
        <span class="fill"></span>
        <span class="glyph">0</span>
      </span>
      None completed (0%)
    </span>
    <span class="heat-legend-item">
      <span class="heat heat-swatch heat-none" aria-hidden="true">
        <span class="fill"></span>
        <span class="glyph">–</span>
      </span>
      No surveys expected
    </span>
    <span class="heat-legend-item">
      <span class="heat heat-swatch heat-future" aria-hidden="true">
        <span class="fill"></span>
        <span class="glyph">·</span>
      </span>
      Scheduled
    </span>
  </div>
  <div class="table-wrap">
    <table class="acquisition">
      <caption class="sr-only">
        Completed surveys against invitations still listed, grouped into Monday–Sunday weeks in each participant's timezone.
      </caption>
      <thead>
        <tr>
          <th>Participant</th>
          <th>Status</th>
          <th>{span === "7" ? "Last 7 local days (Mon–Sun)" : "Study weeks (Mon–Sun)"}</th>
          <th>On screen</th>
          <th>To date</th>
        </tr>
      </thead>
      <tbody>
        {#each shown as row (row.contactId)}
          {@const days = rowWindow(row, span)}
          {@const weeks = groupByWeeks(days)}
          {@const window = windowSummary(days)}
          <tr>
            <td>
              <div class:mono={app.hidePhi}>
                {participantLabel(app.hidePhi, row.displayName, row.extRef, row.contactId)}
              </div>
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
              <div class="week-grid">
                <div class="week-head" aria-hidden="true">
                  <span></span>
                  {#each WEEKDAY_HEADERS as dow, col (col)}
                    <span class="week-dow" class:weekend={dow.weekend} title={dow.full}>
                      {dow.short}
                    </span>
                  {/each}
                </div>
                {#each weeks as week (week.monday)}
                  <div class="week-row">
                    <span class="week-label">{week.label}</span>
                    {#each week.cells as cell, col (col)}
                      {#if cell === null}
                        <span class="heat-pad" class:weekend={col >= 5} aria-hidden="true"></span>
                      {:else}
                        <button
                          type="button"
                          class="heat heat-{heatOf(cell)}"
                          class:weekend={col >= 5}
                          aria-label={dayLabel(cell)}
                          onmouseenter={(e) => openDayHover(e, cell)}
                          onmouseleave={() => closeDayHover(cell)}
                          onfocus={(e) => openDayHover(e, cell)}
                          onblur={() => closeDayHover(cell)}
                        >
                          <span class="fill" aria-hidden="true"></span>
                          <span class="glyph">{dayGlyph(cell)}</span>
                        </button>
                      {/if}
                    {/each}
                  </div>
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

{#if hovered && hoveredDetail}
  <div
    class="heat-popover"
    class:below={hovered.below}
    role="tooltip"
    style="left: {hovered.left}px; top: {hovered.top}px;"
  >
    <div class="heat-popover-head">
      <strong>{hoveredDetail.heading}</strong>
      {#if hoveredDetail.isWeekend}
        <span class="badge muted">Weekend</span>
      {/if}
    </div>
    <div class="heat-popover-summary">{hoveredDetail.summary}</div>
    {#if hoveredDetail.laterNote}
      <div class="heat-popover-later">{hoveredDetail.laterNote}</div>
    {/if}
    {#if hoveredDetail.prompts.length > 0}
      <ul class="heat-popover-prompts">
        {#each hoveredDetail.prompts as prompt, idx (idx)}
          <li>
            <span class="mono">{prompt.sendLocal}</span>
            <span class="prompt-method">{prompt.method === "email" ? "Email" : "SMS"}</span>
            <span class="prompt-status status-{prompt.status}">
              {promptStatusLabel(prompt.status)}
            </span>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}
