<script lang="ts">
  import { errorMessage } from "../lib/types";

  interface Option {
    id: string;
    label: string;
  }

  let {
    label,
    value = $bindable(""),
    loader,
    placeholder = "Select…",
    disabled = false,
    hint = "",
  }: {
    label: string;
    value: string;
    loader: () => Promise<Option[]>;
    placeholder?: string;
    disabled?: boolean;
    hint?: string;
  } = $props();

  let options = $state<Option[]>([]);
  let loading = $state(false);
  let error = $state("");
  let loaded = $state(false);

  async function load(force = false) {
    loading = true;
    error = "";
    try {
      options = await loader();
      loaded = true;
    } catch (e) {
      error = errorMessage(e);
    } finally {
      loading = false;
    }
  }

  // The current value may not be in the list (offline, or an id typed by hand);
  // keep it selectable so opening the form never silently clears a saved setting.
  let valueMissing = $derived(
    value !== "" && loaded && !options.some((o) => o.id === value),
  );
</script>

<div class="field">
  <div class="row" style="justify-content: space-between; margin-bottom: 0.25rem;">
    <label for={`dd-${label}`}>{label}</label>
    <button
      type="button"
      class="link"
      onclick={() => load(true)}
      disabled={disabled || loading}
    >
      {loading ? "Loading…" : loaded ? "Refresh" : "Load from Qualtrics"}
    </button>
  </div>

  {#if loaded && !error}
    <select id={`dd-${label}`} bind:value {disabled}>
      <option value="">{placeholder}</option>
      {#if valueMissing}
        <option value={value}>{value} (not in list)</option>
      {/if}
      {#each options as option (option.id)}
        <option value={option.id}>{option.label}</option>
      {/each}
    </select>
  {:else}
    <input
      id={`dd-${label}`}
      type="text"
      bind:value
      {disabled}
      placeholder="Enter the ID, or load the list above"
    />
  {/if}

  {#if error}
    <div class="hint" style="color: var(--danger);">
      Could not load the list: {error} You can still type the ID by hand.
    </div>
  {:else if hint}
    <div class="hint">{hint}</div>
  {/if}
</div>
