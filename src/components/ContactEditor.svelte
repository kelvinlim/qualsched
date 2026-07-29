<script lang="ts">
  import type { ContactView } from "../lib/types";

  /** Identity fields, matching CORE_FIELDS in the Rust contacts module. */
  const CORE = [
    { key: "firstName", label: "First name" },
    { key: "lastName", label: "Last name" },
    { key: "email", label: "Email address" },
    { key: "phone", label: "Phone number" },
    { key: "extRef", label: "External reference" },
  ] as const;

  /** Embedded-data keys that drive scheduling. */
  const SCHEDULING = [
    { key: "StartDate", label: "Start date", hint: "YYYY-MM-DD" },
    { key: "NumDays", label: "Number of days", hint: "must be above 0 to schedule" },
    { key: "TimeSlots", label: "Time slots", hint: "e.g. 800,1200,1600,2000" },
    { key: "TimeZone", label: "Time zone", hint: "" },
    { key: "ContactMethod", label: "Contact method", hint: "sms or email" },
    { key: "ExpireMinutes", label: "Link expires after (min)", hint: "" },
    { key: "SurveysScheduled", label: "Surveys scheduled", hint: "0 makes them eligible again" },
    { key: "DeleteUnsent", label: "Delete unsent", hint: "1 marks pending invitations for cancellation" },
  ] as const;

  let {
    contact = null,
    busy = false,
    onsave,
    oncancel,
  }: {
    /** null when adding a new participant. */
    contact?: ContactView | null;
    busy?: boolean;
    onsave: (core: Record<string, string>, embedded: Record<string, string>) => void;
    oncancel: () => void;
  } = $props();

  const isNew = $derived(contact === null);

  let core = $state<Record<string, string>>({});
  let embedded = $state<Record<string, string>>({});

  // Reset the form whenever a different participant (or "new") is opened.
  $effect(() => {
    const source = contact;
    const nextCore: Record<string, string> = {};
    const nextEmbedded: Record<string, string> = {};
    for (const { key } of CORE) {
      nextCore[key] =
        source === null
          ? ""
          : ((source as unknown as Record<string, string>)[key] ?? "");
    }
    for (const { key } of SCHEDULING) {
      nextEmbedded[key] = source?.embedded[key] ?? "";
    }
    core = nextCore;
    embedded = nextEmbedded;
  });

  function submit() {
    if (isNew) {
      // Blank embedded fields fall through to the project defaults on the backend.
      const filled = Object.fromEntries(
        Object.entries(embedded).filter(([, v]) => v.trim() !== ""),
      );
      onsave({ ...core }, filled);
      return;
    }
    // Send only what actually changed, so an untouched field is never rewritten.
    const changedCore: Record<string, string> = {};
    const changedEmbedded: Record<string, string> = {};
    for (const { key } of CORE) {
      const before = (contact as unknown as Record<string, string>)[key] ?? "";
      if (core[key] !== before) changedCore[key] = core[key];
    }
    for (const { key } of SCHEDULING) {
      if (embedded[key] !== (contact!.embedded[key] ?? "")) {
        changedEmbedded[key] = embedded[key];
      }
    }
    if (Object.keys(changedCore).length === 0 && Object.keys(changedEmbedded).length === 0) {
      oncancel();
      return;
    }
    onsave(changedCore, changedEmbedded);
  }

  let identityMissing = $derived(
    CORE.every(({ key }) => (core[key] ?? "").trim() === ""),
  );
</script>

<div class="card">
  <h2>
    {isNew
      ? "Add a participant"
      : `Editing ${[contact?.firstName, contact?.lastName].filter(Boolean).join(" ") || contact?.contactId}`}
  </h2>

  <h3>Who they are</h3>
  <div class="grid3">
    {#each CORE as field (field.key)}
      <div class="field">
        <label for={`core-${field.key}`}>{field.label}</label>
        <input id={`core-${field.key}`} type="text" bind:value={core[field.key]} />
        {#if field.key === "phone"}
          <div class="hint">Include the country code, e.g. 16125551234.</div>
        {/if}
      </div>
    {/each}
  </div>

  <h3>Scheduling</h3>
  {#if isNew}
    <div class="hint" style="margin-bottom: 0.6rem;">
      Leave a field blank to use the survey profile's default.
    </div>
  {/if}
  <div class="grid3">
    {#each SCHEDULING as field (field.key)}
      <div class="field">
        <label for={`emb-${field.key}`}>{field.label}</label>
        {#if field.key === "ContactMethod"}
          <select id={`emb-${field.key}`} bind:value={embedded[field.key]}>
            <option value="">(profile default)</option>
            <option value="sms">sms</option>
            <option value="email">email</option>
          </select>
        {:else}
          <input id={`emb-${field.key}`} type="text" bind:value={embedded[field.key]} />
        {/if}
        {#if field.hint}<div class="hint">{field.hint}</div>{/if}
      </div>
    {/each}
  </div>

  {#if identityMissing}
    <div class="hint" style="color: var(--danger);">
      Enter at least a name, email address or phone number.
    </div>
  {/if}

  <div class="row end" style="margin-top: 0.5rem;">
    <button onclick={oncancel} disabled={busy}>Cancel</button>
    <button class="primary" onclick={submit} disabled={busy || identityMissing}>
      {busy ? "Saving…" : isNew ? "Add to mailing list" : "Save to Qualtrics"}
    </button>
  </div>
</div>
