<script lang="ts">
  import { getVersion } from "@tauri-apps/api/app";

  import { app, type ScreenName } from "./lib/state.svelte";
  import { errorMessage } from "./lib/types";

  import AccountsScreen from "./screens/AccountsScreen.svelte";
  import ProjectScreen from "./screens/ProjectScreen.svelte";
  import ContactsScreen from "./screens/ContactsScreen.svelte";
  import ScheduleScreen from "./screens/ScheduleScreen.svelte";
  import DistributionsScreen from "./screens/DistributionsScreen.svelte";
  import ImportWizard from "./screens/ImportWizard.svelte";

  let loadError = $state("");
  // Read from the bundle rather than hardcoded, so it tracks tauri.conf.json.
  let version = $state("");

  $effect(() => {
    app.load().catch((e) => (loadError = errorMessage(e)));
    getVersion()
      .then((v) => (version = v))
      .catch(() => (version = ""));
  });

  const nav: { screen: ScreenName; label: string; needsProject: boolean }[] = [
    { screen: "accounts", label: "Accounts", needsProject: false },
    { screen: "project", label: "Survey profile", needsProject: false },
    { screen: "contacts", label: "Contacts", needsProject: true },
    { screen: "schedule", label: "Schedule", needsProject: true },
    { screen: "distributions", label: "Distributions", needsProject: true },
    { screen: "import", label: "Import old config", needsProject: false },
  ];
</script>

<div class="layout">
  <nav class="sidebar">
    <div class="brand">
      QualSched
      {#if version}<span class="version">v{version}</span>{/if}
    </div>
    {#each nav as item (item.screen)}
      <button
        class="nav"
        class:active={app.screen === item.screen}
        disabled={item.needsProject && !app.hasProject}
        onclick={() => app.go(item.screen)}
      >
        {item.label}
      </button>
    {/each}

    <div class="context">
      {#if app.account}
        <div><strong>{app.account.name}</strong></div>
        <div>{app.account.dataCenter || "no data center set"}</div>
        {#if app.project}
          <div style="margin-top: 0.4rem;">{app.project.name}</div>
        {:else}
          <div style="margin-top: 0.4rem;">No survey profile selected</div>
        {/if}
      {:else}
        <div>No account selected</div>
      {/if}
    </div>
  </nav>

  <main>
    {#if loadError}
      <div class="banner error">Could not load your settings: {loadError}</div>
    {/if}

    {#if !app.loaded}
      <div class="empty">Loading…</div>
    {:else if app.screen === "accounts"}
      <AccountsScreen />
    {:else if app.screen === "project"}
      <ProjectScreen />
    {:else if app.screen === "contacts"}
      <ContactsScreen />
    {:else if app.screen === "schedule"}
      <ScheduleScreen />
    {:else if app.screen === "distributions"}
      <DistributionsScreen />
    {:else if app.screen === "import"}
      <ImportWizard />
    {/if}
  </main>
</div>
