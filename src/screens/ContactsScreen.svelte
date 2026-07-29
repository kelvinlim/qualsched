<script lang="ts">
  import * as api from "../lib/api";
  import { app } from "../lib/state.svelte";
  import { errorMessage, type ContactView } from "../lib/types";
  import ContactEditor from "../components/ContactEditor.svelte";
  import ConfirmDialog from "../components/ConfirmDialog.svelte";

  /** Embedded-data keys shown as table columns, in the order they read best. */
  const COLUMNS = ["StartDate", "NumDays", "TimeSlots", "TimeZone", "ContactMethod"];

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

  $effect(() => {
    if (app.hasProject) void load();
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
    selected =
      selected.size === contacts.length
        ? new Set()
        : new Set(contacts.map((c) => c.contactId));
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
    if (!app.account || !app.project || selected.size === 0) return;
    busy = true;
    error = "";
    notice = "";
    try {
      const updated = await api.applyEmbeddedDefaults(
        app.account.id,
        app.project.id,
        [...selected],
      );
      const byId = new Map(updated.map((c) => [c.contactId, c]));
      contacts = contacts.map((c) => byId.get(c.contactId) ?? c);
      notice = `Filled in missing values for ${updated.length} participant(s).`;
      selected = new Set();
    } catch (e) {
      error = errorMessage(e);
    } finally {
      busy = false;
    }
  }

  function displayName(c: ContactView): string {
    const name = `${c.firstName} ${c.lastName}`.trim();
    return name || c.email || c.phone || c.contactId;
  }

  let eligibleCount = $derived(contacts.filter((c) => c.eligible).length);
</script>

<h1>Contacts</h1>
<p class="subtitle">
  Participants in <strong>{app.project?.name ?? ""}</strong>'s mailing list, with the
  embedded data that decides when they get invitations.
</p>

{#if error}<div class="banner error">{error}</div>{/if}
{#if notice}<div class="banner ok">{notice}</div>{/if}

<div class="row" style="margin-bottom: 0.85rem;">
  <button class="primary" onclick={() => (editor = "new")} disabled={busy}>
    + Add participant
  </button>
  <button onclick={load} disabled={loading}>{loading ? "Loading…" : "Refresh"}</button>
  <button onclick={applyDefaults} disabled={busy || selected.size === 0}>
    Fill in missing values ({selected.size})
  </button>
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

{#if contacts.length === 0 && !loading}
  <div class="empty">
    No participants in this mailing list, or the list ID is not set on the profile.
  </div>
{:else}
  <div class="card scroll-x" style="padding: 0;">
    <table>
      <thead>
        <tr>
          <th>
            <input
              type="checkbox"
              checked={selected.size > 0 && selected.size === contacts.length}
              onchange={toggleAll}
              aria-label="Select all participants"
            />
          </th>
          <th>Name</th>
          <th>Contact</th>
          {#each COLUMNS as key (key)}
            <th>{key}</th>
          {/each}
          <th>Scheduled</th>
          <th>Status</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {#each contacts as contact (contact.contactId)}
          <tr>
            <td>
              <input
                type="checkbox"
                checked={selected.has(contact.contactId)}
                onchange={() => toggle(contact.contactId)}
                aria-label={`Select ${displayName(contact)}`}
              />
            </td>
            <td>{displayName(contact)}</td>
            <td class="mono">{contact.method === "email" ? contact.email : contact.phone}</td>
            {#each COLUMNS as key (key)}
              <td class="mono">{contact.embedded[key] ?? "—"}</td>
            {/each}
            <td class="mono">{contact.embedded.SurveysScheduled ?? "—"}</td>
            <td class="wrap">
              {#if contact.eligible}
                <span class="badge ok">ready</span>
              {:else}
                <span class="badge muted" title={contact.skipReason ?? ""}>skipped</span>
                <div class="hint">{contact.skipReason}</div>
              {/if}
            </td>
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
