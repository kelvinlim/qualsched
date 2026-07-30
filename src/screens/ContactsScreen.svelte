<script lang="ts">
  import * as api from "../lib/api";
  import { matchesQuery } from "../lib/filter";
  import { app } from "../lib/state.svelte";
  import { errorMessage, type ContactView } from "../lib/types";
  import ContactEditor from "../components/ContactEditor.svelte";
  import ConfirmDialog from "../components/ConfirmDialog.svelte";
  import {
    asNumber,
    asText,
    compareCells,
    nextSort,
    type Cell,
    type SortDir,
  } from "../lib/sort";

  interface Column {
    key: string;
    label: string;
    /** Value used for both sorting and, unless the cell is special-cased, display. */
    value: (c: ContactView) => Cell;
    mono?: boolean;
  }

  /**
   * Table columns in the order they read best. Header labels for embedded data keep the
   * Qualtrics field names, so they match what the editor and Qualtrics itself show.
   */
  const COLUMNS: Column[] = [
    { key: "name", label: "Name", value: (c) => sortableName(c) },
    // Phone and email are shown side by side rather than picking one by ContactMethod:
    // participants can be on either channel, and a blank cell is itself worth seeing.
    { key: "phone", label: "Phone", mono: true, value: (c) => asText(c.phone) },
    { key: "email", label: "Email", mono: true, value: (c) => asText(c.email) },
    { key: "StartDate", label: "StartDate", mono: true, value: (c) => asText(c.embedded.StartDate) },
    { key: "NumDays", label: "NumDays", mono: true, value: (c) => asNumber(c.embedded.NumDays) },
    { key: "TimeSlots", label: "TimeSlots", mono: true, value: (c) => asText(c.embedded.TimeSlots) },
    { key: "TimeZone", label: "TimeZone", mono: true, value: (c) => asText(c.embedded.TimeZone) },
    {
      key: "ContactMethod",
      label: "ContactMethod",
      mono: true,
      value: (c) => asText(c.embedded.ContactMethod),
    },
    {
      key: "SurveysScheduled",
      label: "Scheduled",
      mono: true,
      value: (c) => asNumber(c.embedded.SurveysScheduled),
    },
    { key: "status", label: "Status", value: (c) => c.eligible },
  ];

  let contacts = $state<ContactView[]>([]);
  let selected = $state<Set<string>>(new Set());
  /** null = closed, "new" = adding, otherwise the contact being edited. */
  let editor = $state<ContactView | "new" | null>(null);
  let error = $state("");
  let notice = $state("");
  let busy = $state(false);
  let loading = $state(false);
  let pendingRemoval = $state<ContactView | null>(null);
  let confirmRemove = $state(false);
  let sort = $state<{ key: string; dir: SortDir }>({ key: "name", dir: "asc" });
  let query = $state("");

  $effect(() => {
    if (app.hasProject) void load();
  });

  // Its own effect rather than a line in load(): Refresh should not wipe what was typed.
  $effect(() => {
    void app.selectedProjectId;
    query = "";
  });

  async function load() {
    if (!app.account || !app.project) return;
    loading = true;
    error = "";
    try {
      contacts = await api.getContacts(app.account.id, app.project.id);
      selected = new Set();
    } catch (e) {
      error = errorMessage(e);
    } finally {
      loading = false;
    }
  }

  function toggle(contactId: string) {
    const next = new Set(selected);
    if (next.has(contactId)) next.delete(contactId);
    else next.add(contactId);
    selected = next;
  }

  function toggleAll() {
    const next = new Set(selected);
    // A subset test, not a size comparison: two different sets can be the same size.
    if (matching.length > 0 && matching.every((c) => next.has(c.contactId))) {
      for (const contact of matching) next.delete(contact.contactId);
    } else {
      for (const contact of matching) next.add(contact.contactId);
    }
    selected = next;
  }

  async function save(core: Record<string, string>, embedded: Record<string, string>) {
    if (!app.account || !app.project || editor === null) return;
    busy = true;
    error = "";
    notice = "";
    try {
      if (editor === "new") {
        const created = await api.createContact(
          app.account.id,
          app.project.id,
          core,
          embedded,
        );
        contacts = [...contacts, created];
        // Otherwise the notice announces a row the search is hiding.
        query = "";
        notice = `Added ${displayName(created)} to the mailing list.`;
      } else {
        const updated = await api.updateContact(
          app.account.id,
          app.project.id,
          editor.contactId,
          core,
          embedded,
        );
        contacts = contacts.map((c) =>
          c.contactId === updated.contactId ? updated : c,
        );
        notice = `Updated ${displayName(updated)}.`;
      }
      editor = null;
    } catch (e) {
      error = errorMessage(e);
    } finally {
      busy = false;
    }
  }

  function askRemove(contact: ContactView) {
    pendingRemoval = contact;
    confirmRemove = true;
  }

  async function remove() {
    if (!app.account || !app.project || !pendingRemoval) return;
    const target = pendingRemoval;
    busy = true;
    error = "";
    notice = "";
    try {
      const result = await api.deleteContact(
        app.account.id,
        app.project.id,
        target.contactId,
      );
      contacts = contacts.filter((c) => c.contactId !== target.contactId);
      const next = new Set(selected);
      next.delete(target.contactId);
      selected = next;
      if (editor !== "new" && editor?.contactId === target.contactId) editor = null;
      notice =
        result.cancelled > 0
          ? `Removed ${result.contactName} and cancelled ${result.cancelled} pending invitation(s).`
          : `Removed ${result.contactName} from the mailing list.`;
    } catch (e) {
      error = errorMessage(e);
    } finally {
      busy = false;
      pendingRemoval = null;
    }
  }

  async function applyDefaults() {
    if (!app.account || !app.project || selectedVisible.length === 0) return;
    busy = true;
    error = "";
    notice = "";
    try {
      const applied = selectedVisible;
      const updated = await api.applyEmbeddedDefaults(
        app.account.id,
        app.project.id,
        applied,
      );
      const byId = new Map(updated.map((c) => [c.contactId, c]));
      contacts = contacts.map((c) => byId.get(c.contactId) ?? c);
      notice = `Filled in missing values for ${updated.length} participant(s).`;
      // Drop only what was acted on: anything the search is hiding was never sent.
      const next = new Set(selected);
      for (const id of applied) next.delete(id);
      selected = next;
    } catch (e) {
      error = errorMessage(e);
    } finally {
      busy = false;
    }
  }

  /** Natural order, for prose: "Removed Kelvin Lim from the mailing list." */
  function displayName(c: ContactView): string {
    const name = `${c.firstName} ${c.lastName}`.trim();
    return name || c.email || c.phone || c.contactId;
  }

  /** "Lim, Kelvin" — scannable down a column, and sorts by family name. */
  function sortableName(c: ContactView): string {
    const last = c.lastName.trim();
    const first = c.firstName.trim();
    if (last && first) return `${last}, ${first}`;
    return last || first || c.email || c.phone || c.contactId;
  }

  // Counts the whole mailing list, not the search: this is a statement about who can be
  // scheduled, and scheduling ignores whatever is typed in the search box.
  let eligibleCount = $derived(contacts.filter((c) => c.eligible).length);

  let matching = $derived(
    contacts.filter((c) =>
      // sortableName so a name copied out of the table ("Lim, Kelvin") still matches.
      matchesQuery(query, [c.firstName, c.lastName, sortableName(c), c.phone, c.email]),
    ),
  );

  /** Nothing acts on a row the search is hiding — see the same rule on Distributions. */
  let selectedVisible = $derived(
    matching.filter((c) => selected.has(c.contactId)).map((c) => c.contactId),
  );
  let hiddenSelected = $derived(selected.size - selectedVisible.length);

  let sorted = $derived.by(() => {
    const column = COLUMNS.find((c) => c.key === sort.key);
    if (!column) return matching;
    // Copy first: sort() mutates, and reordering the source array in place would
    // fight the reactive updates that edit and remove make to it.
    return [...matching].sort((a, b) =>
      compareCells(column.value(a), column.value(b), sort.dir),
    );
  });
</script>

<h1>Contacts</h1>
<p class="subtitle">
  Participants in this profile's mailing list, with the embedded data that decides when
  they get invitations.
</p>

{#if error}<div class="banner error">{error}</div>{/if}
{#if notice}<div class="banner ok">{notice}</div>{/if}

<div class="row" style="margin-bottom: 0.85rem;">
  <button class="primary" onclick={() => (editor = "new")} disabled={busy}>
    + Add participant
  </button>
  <button onclick={load} disabled={loading}>{loading ? "Loading…" : "Refresh"}</button>
  <button onclick={applyDefaults} disabled={busy || selectedVisible.length === 0}>
    Fill in missing values ({selectedVisible.length})
  </button>
  <input
    class="search"
    type="search"
    bind:value={query}
    placeholder="Search name, phone or email"
    aria-label="Search participants"
  />
  {#if query.trim()}
    <span class="hint" style="margin: 0;">{matching.length} of {contacts.length} shown</span>
  {/if}
  {#if hiddenSelected > 0}
    <span class="hint" style="margin: 0;">
      {hiddenSelected} selected but hidden
      <button class="link" onclick={() => (selected = new Set())}>clear</button>
    </span>
  {/if}
  <span class="spacer"></span>
  <span class="hint">{eligibleCount} of {contacts.length} ready to schedule</span>
</div>

{#if editor !== null}
  <ContactEditor
    contact={editor === "new" ? null : editor}
    {busy}
    onsave={save}
    oncancel={() => (editor = null)}
  />
{/if}

{#if sorted.length === 0 && !loading}
  <div class="empty">
    {contacts.length === 0
      ? "No participants in this mailing list, or the list ID is not set on the profile."
      : "No participants match this search."}
  </div>
{:else}
  <div class="card scroll-x" style="padding: 0;">
    <table>
      <thead>
        <tr>
          <th>
            <input
              type="checkbox"
              checked={matching.length > 0 && selectedVisible.length === matching.length}
              onchange={toggleAll}
              aria-label="Select all participants"
            />
          </th>
          {#each COLUMNS as column (column.key)}
            <th
              aria-sort={sort.key === column.key
                ? sort.dir === "asc"
                  ? "ascending"
                  : "descending"
                : "none"}
            >
              <button class="sort" onclick={() => (sort = nextSort(sort, column.key))}>
                {column.label}
                <span class="arrow" class:on={sort.key === column.key}>
                  {sort.key === column.key && sort.dir === "desc" ? "▼" : "▲"}
                </span>
              </button>
            </th>
          {/each}
          <th></th>
        </tr>
      </thead>
      <tbody>
        {#each sorted as contact (contact.contactId)}
          <tr>
            <td>
              <input
                type="checkbox"
                checked={selected.has(contact.contactId)}
                onchange={() => toggle(contact.contactId)}
                aria-label={`Select ${displayName(contact)}`}
              />
            </td>
            {#each COLUMNS as column (column.key)}
              {#if column.key === "status"}
                <td class="wrap">
                  {#if contact.eligible}
                    <span class="badge ok">ready</span>
                  {:else}
                    <span class="badge muted" title={contact.skipReason ?? ""}>skipped</span>
                    <div class="hint">{contact.skipReason}</div>
                  {/if}
                </td>
              {:else}
                <td class:mono={column.mono}>{column.value(contact) ?? "—"}</td>
              {/if}
            {/each}
            <td>
              <button class="link" onclick={() => (editor = contact)}>Edit</button>
              <button
                class="link"
                style="color: var(--danger);"
                onclick={() => askRemove(contact)}
                disabled={busy}
              >
                Remove
              </button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}

<ConfirmDialog
  bind:open={confirmRemove}
  title="Remove this participant?"
  body={pendingRemoval
    ? `${displayName(pendingRemoval)} will be taken out of this study's mailing list, and any invitations already booked for them but not yet sent will be cancelled first. They stay in your Qualtrics directory, and survey responses they have already submitted are not affected.`
    : ""}
  confirmLabel="Remove"
  danger
  onconfirm={remove}
/>
