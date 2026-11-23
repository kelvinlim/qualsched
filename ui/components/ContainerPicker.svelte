<script lang="ts">
  import { untrack } from "svelte";
  import BusyMark from "./BusyMark.svelte";
  import {
    ALL_CONTAINERS,
    filterPickerOptions,
    overrideToSave,
    type PickerItem,
  } from "../lib/container-resolve";
  import { sortQualtricsOptions } from "../lib/option-sort";
  import { errorMessage, type IdName } from "../lib/types";

  let {
    label,
    containerLabel,
    allLabel,
    value = $bindable(""),
    containerOverride = $bindable<string | undefined>(""),
    defaultContainerId,
    loadContainers,
    loadItems,
    placeholder = "Select…",
    disabled = false,
    hint = "",
  }: {
    label: string;
    containerLabel: string;
    allLabel: string;
    value: string;
    containerOverride?: string;
    defaultContainerId: string;
    loadContainers: (force: boolean) => Promise<IdName[]>;
    loadItems: (containerId: string, force: boolean) => Promise<PickerItem[]>;
    placeholder?: string;
    disabled?: boolean;
    hint?: string;
  } = $props();

  const uid = Math.random().toString(36).slice(2, 9);
  let scope = $state(
    untrack(
      () => (containerOverride ?? "").trim() || defaultContainerId.trim() || ALL_CONTAINERS,
    ),
  );
  let search = $state("");
  let containers = $state<IdName[]>([]);
  let options = $state<PickerItem[]>([]);
  let loading = $state(false);
  let loadOp = $state(0);
  let error = $state("");
  let loaded = $state(false);

  let savedOverride = $derived((containerOverride ?? "").trim());
  let trimmedDefault = $derived(defaultContainerId.trim());
  let effectiveOverride = $derived(
    savedOverride && savedOverride !== trimmedDefault ? savedOverride : "",
  );

  let sortedContainers = $derived(
    [...containers]
      .filter((c) => c.id !== trimmedDefault)
      .sort((a, b) => a.name.localeCompare(b.name)),
  );

  let overrideMissingFromContainers = $derived(
    Boolean(
      savedOverride &&
        savedOverride !== trimmedDefault &&
        !containers.some((c) => c.id === savedOverride),
    ),
  );

  let filtered = $derived(filterPickerOptions(options, search));

  let selectedOption = $derived(options.find((o) => o.id === value) ?? null);
  let selectedNotInFiltered = $derived(
    value !== "" && loaded && !filtered.some((o) => o.id === value),
  );

  function containerDisplay(id: string): string {
    const trimmed = id.trim();
    if (!trimmed) return "";
    const match = containers.find((c) => c.id === trimmed);
    return match ? `${match.name} (${match.id})` : trimmed;
  }

  async function load(force = false, targetScope?: string) {
    const nextScope =
      targetScope ?? (scope || trimmedDefault || ALL_CONTAINERS);
    scope = nextScope;
    const op = ++loadOp;
    loading = true;
    error = "";
    try {
      const containersPromise =
        force || containers.length === 0
          ? loadContainers(force)
              .then((list) => {
                if (op === loadOp) containers = list;
              })
              .catch(() => {
                // Scope selector still works with default / ALL_CONTAINERS.
              })
          : Promise.resolve();

      const [items] = await Promise.all([
        loadItems(nextScope, force),
        containersPromise,
      ]);
      if (op !== loadOp) return;
      options = sortQualtricsOptions(items);
      loaded = true;
    } catch (e) {
      if (op === loadOp) error = errorMessage(e);
    } finally {
      if (op === loadOp) loading = false;
    }
  }

  async function searchAll() {
    scope = ALL_CONTAINERS;
    await load(false, ALL_CONTAINERS);
  }

  async function onScopeChange(event: Event) {
    const nextScope = (event.currentTarget as HTMLSelectElement).value;
    scope = nextScope;
    await load(false, nextScope);
  }

  function onSelectItem(event: Event) {
    const nextId = (event.currentTarget as HTMLSelectElement).value;
    value = nextId;
    if (!nextId) {
      containerOverride = "";
      return;
    }
    const picked = options.find((o) => o.id === nextId);
    if (picked?.containerId) {
      containerOverride = overrideToSave(picked.containerId, defaultContainerId);
    }
  }

  async function resetOverride() {
    containerOverride = "";
    if (trimmedDefault) {
      scope = trimmedDefault;
      if (loaded) await load(false, trimmedDefault);
    }
  }
</script>

<div class="field">
  <div class="row" style="justify-content: space-between; margin-bottom: 0.25rem;">
    <label for={`cp-val-${uid}`}>{label}</label>
    <div class="row" style="gap: 0.65rem;">
      {#if !loaded || scope !== ALL_CONTAINERS}
        <button
          type="button"
          class="link"
          onclick={searchAll}
          disabled={disabled || loading}
        >
          Search {allLabel.toLowerCase()}
        </button>
      {/if}
      <button
        type="button"
        class="link"
        onclick={() => load(true)}
        disabled={disabled || loading}
      >
        {#if loading}
          <BusyMark operation={`cp-${uid}-${loadOp}`} label="Loading" />
        {:else}
          {loaded ? "Refresh" : "Load from Qualtrics"}
        {/if}
      </button>
    </div>
  </div>

  {#if loaded && !error}
    <div class="picker-controls">
      <select
        class="picker-scope"
        value={scope}
        onchange={onScopeChange}
        disabled={disabled || loading}
        aria-label={`${label} ${containerLabel.toLowerCase()}`}
      >
        <option value={ALL_CONTAINERS}>{allLabel}</option>
        {#if trimmedDefault}
          <option value={trimmedDefault}>
            Account default: {containerDisplay(trimmedDefault)}
          </option>
        {/if}
        {#if overrideMissingFromContainers}
          <option value={savedOverride}>{savedOverride} (saved override)</option>
        {/if}
        {#each sortedContainers as container (container.id)}
          <option value={container.id}>{container.name} ({container.id})</option>
        {/each}
      </select>

      <input
        type="search"
        class="picker-search"
        bind:value={search}
        {disabled}
        aria-label={`Filter ${label.toLowerCase()}`}
        placeholder={`Filter by name, ID, or ${containerLabel.toLowerCase()}…`}
      />
    </div>

    <select id={`cp-val-${uid}`} {value} onchange={onSelectItem} {disabled}>
      <option value="">{placeholder}</option>
      {#if selectedNotInFiltered}
        <option value={value}>
          {selectedOption
            ? `${selectedOption.label} (outside filter)`
            : `${value} (not in ${scope === ALL_CONTAINERS ? "list" : "this " + containerLabel.toLowerCase()})`}
        </option>
      {/if}
      {#each filtered as option (`${option.containerId}:${option.id}`)}
        <option value={option.id}>{option.label}</option>
      {/each}
    </select>

    {#if search.trim()}
      <div class="hint">
        Showing {filtered.length} of {options.length}
      </div>
    {/if}
  {:else}
    <input
      id={`cp-val-${uid}`}
      type="text"
      bind:value
      {disabled}
      placeholder="Enter the ID, or load the list above"
    />
  {/if}

  {#if effectiveOverride}
    <div class="hint picker-override-note">
      {#if trimmedDefault}
        Using {containerLabel.toLowerCase()}
        <span class="mono">{containerDisplay(effectiveOverride)}</span>
        (account default: <span class="mono">{containerDisplay(trimmedDefault)}</span>).
        <button type="button" class="link" onclick={resetOverride} {disabled}>
          Use account default
        </button>
      {:else}
        Using {containerLabel.toLowerCase()}
        <span class="mono">{containerDisplay(effectiveOverride)}</span>.
        <button type="button" class="link" onclick={resetOverride} {disabled}>
          Clear
        </button>
      {/if}
    </div>
  {/if}

  {#if error}
    <div class="hint" style="color: var(--danger);">
      Could not load the list: {error} You can still type the ID by hand.
    </div>
  {:else if hint}
    <div class="hint">{hint}</div>
  {/if}
</div>
