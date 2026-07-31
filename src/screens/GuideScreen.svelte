<script lang="ts" module>
  import { marked } from "marked";
  import { gfmHeadingId } from "marked-gfm-heading-id";
  import guideSource from "../../docs/USER_GUIDE.md?raw";

  marked.use(gfmHeadingId(), {
    renderer: {
      // The guide's screenshots (docs/images/) are not written yet; render nothing
      // rather than a broken-image placeholder.
      image: () => "",
    },
  });

  // Parsed once when the module first loads, not on every visit to the screen.
  const guideHtml = marked.parse(guideSource) as string;
</script>

<script lang="ts">
  $effect(() => {
    // <main> keeps its scroll position across screen switches; the guide should
    // always open at the top.
    document.querySelector("main")?.scrollTo(0, 0);
  });

  function onClick(event: MouseEvent) {
    const link = (event.target as HTMLElement).closest("a");
    if (!link) return;
    // Never let the webview navigate away: real navigation would replace the app
    // UI. Only in-page anchors are followed; external links are ignored here.
    event.preventDefault();
    const href = link.getAttribute("href") ?? "";
    if (href.startsWith("#")) {
      document
        .getElementById(decodeURIComponent(href.slice(1)))
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }
</script>

<!-- The delegated handler only acts on <a> elements, which are keyboard-activatable
     natively, so the wrapper itself needs no key handling or role. -->
<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="guide" onclick={onClick}>
  {@html guideHtml}
</div>
