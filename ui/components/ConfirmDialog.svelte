<script lang="ts">
  let {
    open = $bindable(false),
    title,
    body,
    confirmLabel = "Confirm",
    danger = false,
    onconfirm,
  }: {
    open: boolean;
    title: string;
    body: string;
    confirmLabel?: string;
    danger?: boolean;
    onconfirm: () => void;
  } = $props();

  let dialog = $state<HTMLDialogElement | undefined>();

  $effect(() => {
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  });
</script>

<dialog bind:this={dialog} onclose={() => (open = false)}>
  <h2>{title}</h2>
  <p>{body}</p>
  <div class="row end">
    <button type="button" onclick={() => (open = false)}>Cancel</button>
    <button
      type="button"
      class={danger ? "danger" : "primary"}
      onclick={() => {
        open = false;
        onconfirm();
      }}
    >
      {confirmLabel}
    </button>
  </div>
</dialog>
