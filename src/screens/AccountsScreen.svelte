<script lang="ts">
  import * as api from "../lib/api";
  import * as cache from "../lib/cache.svelte";
  import { app, newAccount } from "../lib/state.svelte";
  import { errorMessage, type Account } from "../lib/types";
  import ApiDropdown from "../components/ApiDropdown.svelte";
  import ConfirmDialog from "../components/ConfirmDialog.svelte";

  let draft = $state<Account | null>(null);
  let tokenInput = $state("");
  let tokenStored = $state(false);
  let error = $state("");
  let notice = $state("");
  let busy = $state(false);
  let confirmDelete = $state(false);

  // Reload the form whenever the selected account changes.
  $effect(() => {
    const account = app.account;
    draft = account ? $state.snapshot(account) : null;
    tokenInput = "";
    error = "";
    notice = "";
    if (account) {
      api
        .hasAccountToken(account.id)
        .then((has) => (tokenStored = has))
        .catch(() => (tokenStored = false));
    } else {
      tokenStored = false;
    }
  });

  function addAccount() {
    const account = newAccount();
    app.apply({ ...app.config, accounts: [...app.config.accounts, account] });
    app.select(account.id);
  }

  async function save() {
    if (!draft) return;
    busy = true;
    error = "";
    notice = "";
    try {
      const id = draft.id;
      app.apply(await api.saveAccount($state.snapshot(draft)));
      if (tokenInput.trim()) {
        await api.setAccountToken(id, tokenInput.trim());
        tokenInput = "";
        tokenStored = true;
      }
      cache.invalidateAccount(id);
      notice = "Saved.";
    } catch (e) {
      error = errorMessage(e);
    } finally {
      busy = false;
    }
  }

  async function test() {
    if (!draft) return;
    busy = true;
    error = "";
    notice = "";
    try {
      const result = await api.testAccount(draft.id);
      notice = result.message;
    } catch (e) {
      error = errorMessage(e);
    } finally {
      busy = false;
    }
  }

  async function removeAccount() {
    if (!draft) return;
    busy = true;
    error = "";
    try {
      app.apply(await api.deleteAccount(draft.id));
      cache.invalidateAccount(draft.id);
      app.select(app.config.accounts[0]?.id ?? null);
    } catch (e) {
      error = errorMessage(e);
    } finally {
      busy = false;
    }
  }

  async function forgetToken() {
    if (!draft) return;
    try {
      await api.clearAccountToken(draft.id);
      tokenStored = false;
      notice = "Token removed from the system keychain.";
    } catch (e) {
      error = errorMessage(e);
    }
  }
</script>

<h1>Accounts</h1>
<p class="subtitle">
  An account is one Qualtrics login: its API token, data center, contact directory and
  message library. Each account can hold several survey profiles.
</p>

<div class="row" style="align-items: flex-start; gap: 1.25rem;">
  <div style="width: 15rem; flex-shrink: 0;">
    {#each app.config.accounts as account (account.id)}
      <button
        class="list-item"
        class:active={account.id === app.selectedAccountId}
        style="width: 100%; text-align: left;"
        onclick={() => app.select(account.id)}
      >
        <span>{account.name || "(unnamed)"}</span>
        <span class="spacer"></span>
        <span class="badge muted">{account.dataCenter || "?"}</span>
      </button>
    {/each}
    <button style="width: 100%; margin-top: 0.35rem;" onclick={addAccount}>
      + Add account
    </button>
  </div>

  <div style="flex: 1; min-width: 0;">
    {#if !draft}
      <div class="empty">
        No account yet. Add one, or import an existing config file from the sidebar.
      </div>
    {:else}
      {#if error}<div class="banner error">{error}</div>{/if}
      {#if notice}<div class="banner ok">{notice}</div>{/if}

      <div class="card">
        <h2>Connection</h2>

        <div class="grid2">
          <div class="field">
            <label for="acc-name">Account name</label>
            <input id="acc-name" type="text" bind:value={draft.name} />
          </div>
          <div class="field">
            <label for="acc-dc">Data center</label>
            <input
              id="acc-dc"
              type="text"
              bind:value={draft.dataCenter}
              placeholder="yul1, ca1, gov1, iad1"
            />
            <div class="hint">
              The subdomain in your Qualtrics URL. Find it under Account Settings →
              Qualtrics IDs.
            </div>
          </div>
        </div>

        <div class="field">
          <label for="acc-token">API token</label>
          <input
            id="acc-token"
            type="password"
            bind:value={tokenInput}
            placeholder={tokenStored ? "Stored — type a new one to replace it" : "Paste your API token"}
          />
          <div class="hint">
            Kept in your operating system's keychain, never in the settings file.
            {#if tokenStored}
              <button type="button" class="link" onclick={forgetToken}>Remove stored token</button>
            {/if}
          </div>
        </div>

        <div class="checkbox">
          <input id="acc-verify" type="checkbox" bind:checked={draft.verifyTls} />
          <label for="acc-verify">Verify TLS certificates</label>
        </div>
        <div class="hint" style="margin-top: -0.5rem; margin-bottom: 0.85rem;">
          Leave this on. Turn it off only for a deployment behind TLS interception, such
          as the VA's gov1 data center.
        </div>
      </div>

      <div class="card">
        <h2>Directory and library</h2>
        <ApiDropdown
          label="Contact directory"
          bind:value={draft.defaultDirectory}
          hint="The XM Directory (contact pool) holding your mailing lists."
          loader={async () =>
            (await cache.directories(draft!.id)).map((d) => ({
              id: d.id,
              label: `${d.name} (${d.id})`,
            }))}
        />
        <div class="field">
          <label for="acc-lib">Message library ID</label>
          <input
            id="acc-lib"
            type="text"
            bind:value={draft.libraryId}
            placeholder="GR_… or UR_…"
          />
          <div class="hint">
            Holds your invitation templates. A group library starts with GR_, a personal
            one with UR_.
          </div>
        </div>
      </div>

      <div class="row">
        <button class="primary" onclick={save} disabled={busy}>Save</button>
        <button onclick={test} disabled={busy}>Test connection</button>
        <span class="spacer"></span>
        <button class="danger" onclick={() => (confirmDelete = true)} disabled={busy}>
          Delete account
        </button>
      </div>

      <ConfirmDialog
        bind:open={confirmDelete}
        title="Delete this account?"
        body={`"${draft.name}" and its ${draft.projects.length} survey profile(s) will be removed from QualSched, along with its stored token. Nothing in Qualtrics is changed.`}
        confirmLabel="Delete"
        danger
        onconfirm={removeAccount}
      />
    {/if}
  </div>
</div>
