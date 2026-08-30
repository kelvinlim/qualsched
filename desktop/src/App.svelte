<script lang="ts">
  import { getVersion } from "@tauri-apps/api/app";

  import * as api from "@qualsched/api";
  import ChangelogPanel from "@qualsched/ui/components/ChangelogPanel.svelte";
  import { NAV_ITEMS, navItemDisabled, navItemTitle } from "@qualsched/ui/lib/nav";
  import { app } from "@qualsched/ui/lib/state.svelte";
  import { errorMessage, type UpdateInfo } from "@qualsched/ui/lib/types";
  import AccountsScreen from "@qualsched/ui/screens/AccountsScreen.svelte";
  import ContactsScreen from "@qualsched/ui/screens/ContactsScreen.svelte";
  import DistributionsScreen from "@qualsched/ui/screens/DistributionsScreen.svelte";
  import ExportScreen from "@qualsched/ui/screens/ExportScreen.svelte";
  import GuideScreen from "@qualsched/ui/screens/GuideScreen.svelte";
  import ImportWizard from "@qualsched/ui/screens/ImportWizard.svelte";
  import ProjectScreen from "@qualsched/ui/screens/ProjectScreen.svelte";
  import ScheduleScreen from "@qualsched/ui/screens/ScheduleScreen.svelte";

  let loadError = $state("");
  // Read from the bundle rather than hardcoded, so it tracks tauri.conf.json.
  let version = $state("");

  let changelogOpen = $state(false);
  let update = $state<UpdateInfo | null>(null);
  let checking = $state(false);
  let checkError = $state("");

  const LAST_SEEN_KEY = "qualsched.lastSeenVersion";

  // `silent` is set for the check on launch: being offline is the normal case for
  // a laptop opened before it joins wifi, and must not greet the user with an error.
  async function check(silent: boolean) {
    checking = true;
    checkError = "";
    try {
      update = await api.checkForUpdate();
    } catch (e) {
      if (!silent) checkError = errorMessage(e);
    } finally {
      checking = false;
    }
  }

  $effect(() => {
    app.load().catch((e) => (loadError = errorMessage(e)));
    check(true);
    getVersion()
      .then((v) => {
        version = v;
        // Only after an actual upgrade — a fresh install has nothing to catch up on.
        const seen = localStorage.getItem(LAST_SEEN_KEY);
        if (seen && seen !== v) changelogOpen = true;
        localStorage.setItem(LAST_SEEN_KEY, v);
      })
      .catch(() => (version = ""));
  });

  $effect(() => {
    let cancelled = false;
    let unlisten: (() => void) | undefined;
    // Native menu: open the panel and surface errors (offline, 404) instead of
    // the silent launch-time check.
    void api.onCheckForUpdates(() => {
      changelogOpen = true;
      void check(false);
    }).then((fn) => {
      if (cancelled) fn();
      else unlisten = fn;
    });
    return () => {
      cancelled = true;
      unlisten?.();
    };
  });

</script>

<div class="layout">
  <nav class="sidebar">
    <div class="brand">
      QualSched
      {#if version}<span class="version">v{version}</span>{/if}
    </div>
    {#each NAV_ITEMS as item (item.screen)}
      <button
        class="nav"
        class:active={app.screen === item.screen}
        disabled={navItemDisabled(item, app.hasAccount, app.hasProject)}
        title={navItemTitle(item, app.hasAccount, app.hasProject)}
        onclick={() => app.go(item.screen)}
      >
        {item.label}
      </button>
    {/each}

    <button
      class="nav whats-new"
      title="Release notes for this and earlier versions, and whether a newer one is out"
      onclick={() => (changelogOpen = true)}
    >
      What's new
      {#if update?.updateAvailable}
        <span class="badge update">v{update.latestVersion}</span>
      {/if}
    </button>
  </nav>

  <main>
    <!-- Gated on `loaded`: until the config is in, there is nothing true to say, and on a
         load failure this would otherwise assert "Choose an account" directly above the
         banner explaining that nothing could be read. -->
    {#if app.loaded}
      <nav class="breadcrumb" aria-label="Breadcrumb">
        {#if app.account}
          <button class="link" onclick={() => app.go("accounts")}>
            {app.account.name || "(unnamed account)"}
          </button>
          {#if app.account.dataCenter}
            <span class="badge muted">{app.account.dataCenter}</span>
          {/if}
          <span class="sep" aria-hidden="true">/</span>
          <button class="link" onclick={() => app.go("project")}>
            {app.project
              ? app.project.name || "(unnamed profile)"
              : "Choose a survey profile"}
          </button>
        {:else}
          <button class="link" onclick={() => app.go("accounts")}>Choose an account</button>
        {/if}
      </nav>
    {/if}

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
    {:else if app.screen === "export"}
      <ExportScreen />
    {:else if app.screen === "guide"}
      <GuideScreen />
    {/if}
  </main>
</div>

<ChangelogPanel
  bind:open={changelogOpen}
  {update}
  {checking}
  {checkError}
  oncheck={() => check(false)}
/>
