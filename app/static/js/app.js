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

// A checkbox with data-requires="<name>" only counts when the checkbox <name> in the same form is ticked,
// e.g. descriptions of time entries need the entries. Otherwise it is unticked and greyed out,
// and gets its old state back when <name> is ticked again. The server keeps it too, see accounts/forms.py.
function syncDependentCheckboxes(form) {
  for (const box of form.querySelectorAll("input[data-requires]")) {
    const parent = form.elements[box.dataset.requires];
    if (!parent || box.disabled === !parent.checked) continue;
    if (parent.checked) {
      box.checked = box.dataset.wasChecked === "true";
    } else {
      box.dataset.wasChecked = box.checked;
      box.checked = false;
    }
    box.disabled = !parent.checked;
    box.closest("label")?.classList.toggle("opacity-50", !parent.checked);
  }
}
document.addEventListener("change", (event) => {
  if (event.target.form) syncDependentCheckboxes(event.target.form);
});
document.addEventListener("htmx:load", (event) => {
  for (const form of event.detail.elt.querySelectorAll?.("form") ?? []) syncDependentCheckboxes(form);
});
document.addEventListener("DOMContentLoaded", () => document.querySelectorAll("form").forEach(syncDependentCheckboxes));

// An element with data-shown-for="<name>=<value>" is shown only while the field <name> of its form has
// that value, e.g. the customer access settings only for the role "customer". Hidden, its fields are not sent.
function syncShownFor(form) {
  for (const element of form.querySelectorAll("[data-shown-for]")) {
    const [name, value] = element.dataset.shownFor.split("=");
    const field = form.elements[name];
    if (!field) continue;
    element.hidden = element.disabled = field.value !== value;
  }
}
document.addEventListener("change", (event) => {
  if (event.target.form) syncShownFor(event.target.form);
});

// A list of checkboxes with data-checkbox-group can have a checkbox with data-select-all that ticks or unticks
// all others at once. It is half ticked while only some are, and has no name, so it is not sent.
function syncSelectAll(group) {
  const all = group.querySelector("input[data-select-all]");
  if (!all) return;
  const boxes = [...group.querySelectorAll("input[type=checkbox]:not([data-select-all])")];
  const ticked = boxes.filter((box) => box.checked).length;
  all.checked = ticked > 0 && ticked === boxes.length;
  all.indeterminate = ticked > 0 && ticked < boxes.length;
}
document.addEventListener("change", (event) => {
  const group = event.target.closest?.("[data-checkbox-group]");
  if (!group) return;
  if (event.target.matches("[data-select-all]")) {
    for (const box of group.querySelectorAll("input[type=checkbox]:not([data-select-all])")) {
      box.checked = event.target.checked;
    }
  }
  syncSelectAll(group);
});
document.addEventListener("htmx:load", (event) => {
  event.detail.elt.querySelectorAll?.("[data-checkbox-group]").forEach(syncSelectAll);
});
document.addEventListener("DOMContentLoaded", () => document.querySelectorAll("[data-checkbox-group]").forEach(syncSelectAll));

// Menu button of the top bar on phones: shows or hides the navigation.
document.addEventListener("click", (event) => {
  const toggle = event.target.closest("[data-nav-toggle]");
  if (!toggle) return;
  const open = document.getElementById("sidebar").toggleAttribute("data-open");
  toggle.setAttribute("aria-expanded", open);
});

// Tabs inside a page: a container with data-tabs holds buttons with data-tab="<name>" and panels with
// data-tab-panel="<name>". A click shows its panel and hides the others.
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-tab]");
  const tabs = button?.closest("[data-tabs]");
  if (!tabs) return;
  for (const tab of tabs.querySelectorAll("[data-tab]")) {
    const active = tab === button;
    tab.classList.toggle("tab-active", active);
    tab.setAttribute("aria-selected", active);
  }
  for (const panel of tabs.querySelectorAll("[data-tab-panel]")) {
    panel.hidden = panel.dataset.tabPanel !== button.dataset.tab;
  }
});

// A button with data-copy="<id>" copies the text of the element with that id, e.g. a configuration.
// The clipboard needs HTTPS (or localhost); without it the text is selected for copying by hand.
document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  const source = document.getElementById(button.dataset.copy);
  try {
    await navigator.clipboard.writeText(source.textContent);
  } catch {
    getSelection().selectAllChildren(source);
    return;
  }
  const label = button.dataset.label ?? button.textContent;
  button.dataset.label = label;
  button.textContent = "Kopiert";
  setTimeout(() => (button.textContent = label), 2000);
});

// A file field with data-max-size="<bytes>" refuses larger files before the upload starts; the server would
// cut such a request off without an answer the page could show (see core/upload_limit.py).
document.addEventListener("change", (event) => {
  const input = event.target;
  if (!input.matches?.("input[type=file][data-max-size]")) return;
  const tooBig = [...input.files].some((file) => file.size > Number(input.dataset.maxSize));
  input.setCustomValidity(tooBig ? input.dataset.maxSizeMessage : "");
  input.reportValidity();
});
