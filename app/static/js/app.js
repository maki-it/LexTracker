// The dialog in base.html. Pages are loaded into it by htmx (see core/dialogs.py);
// this only opens and closes it.
document.addEventListener("htmx:afterSwap", (event) => {
  const dialog = document.getElementById("dialog");
  // An empty answer (e.g. "timer started, close the dialog") opens nothing.
  if (event.detail.target.id === "dialog-body" && event.detail.xhr.responseText.trim() && !dialog.open) {
    dialog.showModal();
  }
});

// Runs before htmx (capture phase), so a boosted "Abbrechen" link inside the dialog does not load a page.
document.addEventListener(
  "click",
  (event) => {
    const dialog = document.getElementById("dialog");
    // A click on the dark backdrop around the dialog closes it.
    if (event.target === dialog) {
      const box = dialog.getBoundingClientRect();
      const outside =
        event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom;
      if (outside) dialog.close();
      return;
    }
    // "Abbrechen" links close the dialog when they are inside it, and navigate otherwise.
    const cancel = event.target.closest("[data-close-dialog]");
    if (cancel && cancel.closest("dialog")) {
      event.preventDefault();
      event.stopPropagation();
      cancel.closest("dialog").close();
    }
  },
  true,
);

// The server can close the dialog with the response header "HX-Trigger: close-dialog".
document.body.addEventListener("close-dialog", () => document.getElementById("dialog").close());
