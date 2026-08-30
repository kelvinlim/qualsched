<script lang="ts">
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

  import logo from "./assets/qualsched-icon.png";
  import LegalPage from "./components/LegalPage.svelte";
  import LoginScreen from "./components/LoginScreen.svelte";

  const VERSION = "0.2.2";
  const legalKind = api.legalKindFromPath();

  let loadError = $state("");
  let version = $state(VERSION);
  let me = $state<api.Me | null>(null);
  let authStatus = $state<api.AuthStatus | null>(null);
  let authChecked = $state(false);

  let changelogOpen = $state(false);
  let update = $state<UpdateInfo | null>(null);
  let checking = $state(false);
  let checkError = $state("");

  const LAST_SEEN_KEY = "qualsched.lastSeenVersion";

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
    if (legalKind) return;
    void (async () => {
      try {
        authStatus = await api.authStatus();
        me = await api.me();
        await app.load();
        const seen = localStorage.getItem(LAST_SEEN_KEY);
        if (seen && seen !== version) changelogOpen = true;
        localStorage.setItem(LAST_SEEN_KEY, version);
        void check(true);
      } catch (e) {
        const msg = errorMessage(e);
        const unauth =
          msg.toLowerCase().includes("not authenticated") ||
          (e && typeof e === "object" && "kind" in e && (e as { kind: string }).kind === "Unauthorized");
        if (!unauth) loadError = msg;
      } finally {
        authChecked = true;
      }
    })();
  });

  async function signOut() {
    await api.logout();
    me = null;
    app.loaded = false;
  }

</script>

{#if legalKind}
  <LegalPage kind={legalKind} />
{:else if !authChecked}
  <div class="empty">Loading…</div>
{:else if !me}
  {#if authStatus}
    <LoginScreen status={authStatus} />
  {:else}
    <div class="banner error" style="margin: 2rem;">Could not reach the API. Is the backend running?</div>
  {/if}
{:else}
  <div class="layout">
    <nav class="sidebar">
      <div class="brand">
        <img class="logo" src={logo} alt="" width="28" height="28" />
        <span class="name">QualSched</span>
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

      <div class="session">
        <div class="hint">{me.email}</div>
        <button class="link" type="button" onclick={() => void signOut()}>Sign out</button>
      </div>

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
{/if}
