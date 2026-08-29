<script lang="ts" module>
  import { marked } from "marked";
  import { gfmHeadingId } from "marked-gfm-heading-id";
  import privacySource from "../../docs/PRIVACY.md?raw";
  import termsSource from "../../docs/TERMS.md?raw";

  marked.use(gfmHeadingId());

  const html = {
    privacy: marked.parse(privacySource) as string,
    terms: marked.parse(termsSource) as string,
  };

  const titles = {
    privacy: "Privacy Policy",
    terms: "Terms of Service",
  };
</script>

<script lang="ts">
  import logo from "../assets/qualsched-icon.png";
  import { withBase } from "../lib/api";

  let {
    kind,
  }: {
    kind: "privacy" | "terms";
  } = $props();

  $effect(() => {
    document.title = `${titles[kind]} · QualSched`;
  });
</script>

<div class="legal">
  <header class="legal-bar">
    <a class="home" href={withBase("/")}>
      <img src={logo} alt="" width="28" height="28" />
      QualSched
    </a>
    <nav aria-label="Legal">
      <a href={withBase("/privacy")} aria-current={kind === "privacy" ? "page" : undefined}>
        Privacy
      </a>
      <a href={withBase("/terms")} aria-current={kind === "terms" ? "page" : undefined}>Terms</a>
    </nav>
  </header>
  <div class="guide body">
    {@html html[kind]}
  </div>
</div>

<style>
  .legal {
    min-height: 100vh;
    padding: 1.25rem 1.5rem 3rem;
  }
  .legal-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    max-width: 44rem;
    margin: 0 auto 1.5rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid var(--border);
  }
  .home {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-weight: 650;
    color: var(--text);
    text-decoration: none;
  }
  .home img {
    width: 1.75rem;
    height: 1.75rem;
    border-radius: 0.35rem;
  }
  nav {
    display: flex;
    gap: 1rem;
  }
  nav a {
    color: var(--muted);
    text-decoration: none;
  }
  nav a:hover,
  nav a[aria-current="page"] {
    color: var(--accent);
  }
  nav a[aria-current="page"] {
    font-weight: 600;
  }
  .body {
    margin: 0 auto;
  }
</style>
