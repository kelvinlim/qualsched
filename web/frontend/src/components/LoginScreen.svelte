<script lang="ts">
  import logo from "../assets/qualsched-icon.png";
  import * as api from "@qualsched/api";
  import { errorMessage } from "@qualsched/ui/lib/types";

  let {
    status,
  }: {
    status: api.AuthStatus;
  } = $props();

  let email = $state("");
  let error = $state("");
  let busy = $state(false);

  async function devSignIn() {
    busy = true;
    error = "";
    try {
      await api.devLogin(email.trim());
      window.location.reload();
    } catch (e) {
      error = errorMessage(e);
    } finally {
      busy = false;
    }
  }
</script>

<div class="login">
  <div class="card">
    <div class="login-brand">
      <img src={logo} alt="" width="48" height="48" />
      <h1>QualSched</h1>
    </div>
    <p class="subtitle">
      QualSched is a researcher tool for scheduling Qualtrics EMA invitations.
      Participant records stay in Qualtrics.
    </p>

    {#if error}<div class="banner error">{error}</div>{/if}

    {#if status.google}
      <a class="primary button" href={api.withBase("/auth/login")}>Sign in with Google</a>
      <p class="hint">
        Your Google account must be an @umn.edu address, listed in SUPERADMIN_EMAILS,
        or already in the users table. Gmail is not campus-wide. Google tokens are not stored.
      </p>
    {/if}

    {#if status.devLogin}
      {#if status.google}
        <p class="hint">Or, for local development:</p>
      {:else}
        <p class="hint">
          Google OAuth is not configured. Sign in with an email listed in
          <span class="mono">SUPERADMIN_EMAILS</span>.
        </p>
      {/if}
      <form
        onsubmit={(e) => {
          e.preventDefault();
          void devSignIn();
        }}
      >
        <div class="field">
          <label for="dev-email">Email</label>
          <input
            id="dev-email"
            type="email"
            bind:value={email}
            placeholder="you@umn.edu"
            autocomplete="username"
          />
        </div>
        <button class="primary" type="submit" disabled={busy || !email.trim()}>
          {busy ? "Signing in…" : "Development sign-in"}
        </button>
      </form>
    {/if}

    {#if !status.google && !status.devLogin}
      <div class="banner error">
        No sign-in method is available. Set GOOGLE_CLIENT_ID/SECRET, or run with
        ENVIRONMENT=dev and empty Google client ids.
      </div>
    {/if}

    <nav class="legal-links" aria-label="Legal">
      <a href={api.withBase("/privacy")}>Privacy</a>
      <span aria-hidden="true">·</span>
      <a href={api.withBase("/terms")}>Terms</a>
    </nav>
  </div>
</div>

<style>
  .login {
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 2rem;
  }
  .login .card {
    width: min(26rem, 100%);
    margin: 0;
  }
  .login-brand {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.25rem;
  }
  .login-brand img {
    width: 3rem;
    height: 3rem;
    border-radius: 0.55rem;
  }
  .login-brand h1 {
    margin: 0;
  }
  .button {
    display: inline-block;
    text-align: center;
    text-decoration: none;
    padding: 0.5rem 0.85rem;
    border-radius: var(--radius);
    margin-bottom: 0.75rem;
    background: var(--accent);
    border: 1px solid var(--accent);
    color: #fff;
    font-weight: 600;
  }
  .legal-links {
    display: flex;
    gap: 0.4rem;
    justify-content: center;
    margin-top: 1.25rem;
    font-size: 0.85rem;
  }
  .legal-links a {
    color: var(--muted);
  }
  .legal-links a:hover {
    color: var(--accent);
  }
  .legal-links span {
    color: var(--border);
  }
</style>
