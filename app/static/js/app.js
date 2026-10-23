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
// all others at once. It is half ticked while only some are, and has no name, so it is not sent. A search field
// with data-filter hides the entries that do not match; select all then covers only the entries still shown.
function groupBoxes(group) {
  return [...group.querySelectorAll("input[type=checkbox]:not([data-select-all])")].filter((box) => !box.closest("label").hidden);
}
function syncSelectAll(group) {
  const all = group.querySelector("input[data-select-all]");
  if (!all) return;
  const boxes = groupBoxes(group);
  const ticked = boxes.filter((box) => box.checked).length;
  all.checked = ticked > 0 && ticked === boxes.length;
  all.indeterminate = ticked > 0 && ticked < boxes.length;
  all.disabled = boxes.length === 0;
}
function filterGroup(group, input) {
  const query = input.value.trim().toLocaleLowerCase();
  let shown = 0;
  for (const box of group.querySelectorAll("input[type=checkbox]:not([data-select-all])")) {
    const label = box.closest("label");
    label.hidden = !label.textContent.toLocaleLowerCase().includes(query);
    if (!label.hidden) shown++;
  }
  const none = group.querySelector("[data-no-match]");
  if (none) none.hidden = shown > 0;
  syncSelectAll(group);
}
document.addEventListener("input", (event) => {
  const group = event.target.closest?.("[data-checkbox-group]");
  if (group && event.target.matches("[data-filter]")) filterGroup(group, event.target);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && event.target.matches?.("[data-filter]")) event.preventDefault();
});
document.addEventListener("change", (event) => {
  const group = event.target.closest?.("[data-checkbox-group]");
  if (!group) return;
  if (event.target.matches("[data-select-all]")) {
    for (const box of groupBoxes(group)) box.checked = event.target.checked;
  }
  syncSelectAll(group);
});
document.addEventListener("htmx:load", (event) => {
  event.detail.elt.querySelectorAll?.("[data-checkbox-group]").forEach(syncSelectAll);
});
document.addEventListener("DOMContentLoaded", () => document.querySelectorAll("[data-checkbox-group]").forEach(syncSelectAll));

// A select with data-searchable is shown like the checkbox lists: a search field above a scrollable list of
// radio buttons, so only one entry can be chosen. The select stays in the form (hidden) and is what gets sent.
let searchableCount = 0;
function makeSearchable(select) {
  if (select.dataset.searchReady) return;
  select.dataset.searchReady = "1";
  const group = `searchable-${++searchableCount}`;
  const box = document.createElement("div");
  box.className = "flex max-h-48 flex-col gap-1.5 overflow-y-auto rounded-lg border border-line px-3 py-2";
  const header = document.createElement("div");
  header.className = "sticky -top-2 -mx-3 -mt-2 flex flex-col gap-1.5 border-b border-line bg-surface px-3 pb-1.5 pt-2";
  const input = document.createElement("input");
  input.type = "search";
  input.className = "input";
  input.placeholder = "Suchen …";
  input.autocomplete = "off";
  input.setAttribute("aria-label", "Auswahl durchsuchen");
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") event.preventDefault();
  });
  header.append(input);
  const none = document.createElement("span");
  none.className = "text-sm text-muted";
  none.textContent = "Keine Treffer.";
  none.hidden = true;
  const entries = [...select.options].map((option) => {
    const label = document.createElement("label");
    label.className = "flex items-center gap-2 text-sm";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = group;
    radio.checked = option.selected;
    radio.addEventListener("change", () => {
      select.value = option.value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    label.append(radio, ` ${option.textContent}`);
    // The empty entry ("kein Kunde") stays in the header so it is always at hand.
    (option.value ? box : header).append(label);
    return { label, option };
  });
  input.addEventListener("input", () => {
    const query = input.value.trim().toLocaleLowerCase();
    let shown = 0;
    for (const { label, option } of entries) {
      if (!option.value) continue;
      label.hidden = !option.textContent.toLocaleLowerCase().includes(query);
      if (!label.hidden) shown++;
    }
    none.hidden = shown > 0;
  });
  box.prepend(header);
  box.append(none);
  select.hidden = true;
  select.before(box);
}
document.addEventListener("htmx:load", (event) => {
  event.detail.elt.querySelectorAll?.("select[data-searchable]").forEach(makeSearchable);
});
document.addEventListener("DOMContentLoaded", () => document.querySelectorAll("select[data-searchable]").forEach(makeSearchable));

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

// Task search (tracking/_task_search.html): a search field whose suggestions htmx loads from the server.
// Picking a suggestion puts its id into the hidden field next to it. Typing again clears that id,
// so the form can only be sent with a picked task. Arrow keys move through the suggestions, Enter picks one.
const taskSearchOf = (element) => element?.closest?.("[data-task-search]");
const taskParts = (search) => ({
  input: search.querySelector("input[type=search]"),
  picked: search.querySelector("input[type=hidden]"),
  list: search.querySelector("[role=listbox]"),
});

function showTaskResults(search, open) {
  const { input, list } = taskParts(search);
  list.hidden = !open;
  input.setAttribute("aria-expanded", open);
}

function syncTaskValidity(search) {
  const { input, picked } = taskParts(search);
  input.setCustomValidity(picked.value ? "" : "Bitte eine Aufgabe aus den Vorschlägen auswählen.");
}

function pickTask(search, option) {
  const { input, picked } = taskParts(search);
  picked.value = option.dataset.value;
  input.value = option.dataset.label;
  syncTaskValidity(search);
  showTaskResults(search, false);
}

function moveTaskSelection(search, step) {
  const options = [...taskParts(search).list.querySelectorAll("[role=option]")];
  if (!options.length) return;
  const current = options.findIndex((option) => option.getAttribute("aria-selected") === "true");
  const next = current === -1 ? (step > 0 ? 0 : options.length - 1) : (current + step + options.length) % options.length;
  options.forEach((option, i) => option.setAttribute("aria-selected", i === next));
  options[next].scrollIntoView({ block: "nearest" });
}

document.addEventListener("input", (event) => {
  const search = taskSearchOf(event.target);
  if (!search || event.target.type !== "search") return;
  taskParts(search).picked.value = "";
  syncTaskValidity(search);
});

// While a picked task is shown, the field holds its full name; the suggestions are then the recently used tasks.
document.addEventListener("htmx:configRequest", (event) => {
  const search = taskSearchOf(event.detail.elt);
  if (search && taskParts(search).picked.value) event.detail.parameters.q = "";
});

document.addEventListener("htmx:afterSwap", (event) => {
  const search = taskSearchOf(event.detail.target);
  if (search) showTaskResults(search, search.contains(document.activeElement));
});

// Keeps the focus in the field, so the list stays open until the click picks the suggestion.
document.addEventListener("mousedown", (event) => {
  if (taskSearchOf(event.target) && event.target.closest("[role=option]")) event.preventDefault();
});

document.addEventListener("click", (event) => {
  const option = event.target.closest?.("[role=option]");
  const search = taskSearchOf(option);
  if (search) pickTask(search, option);
});

document.addEventListener("focusout", (event) => {
  const search = taskSearchOf(event.target);
  if (search && !search.contains(event.relatedTarget)) showTaskResults(search, false);
});

document.addEventListener("keydown", (event) => {
  const search = taskSearchOf(event.target);
  if (!search || event.target.type !== "search") return;
  const { list } = taskParts(search);
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    if (list.hidden) showTaskResults(search, true);
    moveTaskSelection(search, event.key === "ArrowDown" ? 1 : -1);
  } else if (event.key === "Enter" && !list.hidden) {
    // Enter picks the marked suggestion (or the first) instead of sending the form.
    const option = list.querySelector("[aria-selected=true]") ?? list.querySelector("[role=option]");
    if (!option) return;
    event.preventDefault();
    pickTask(search, option);
  } else if (event.key === "Escape" && !list.hidden) {
    // Only closes the list, not the dialog around it.
    event.preventDefault();
    showTaskResults(search, false);
  }
});

document.addEventListener("htmx:load", (event) => {
  event.detail.elt.querySelectorAll?.("[data-task-search]").forEach(syncTaskValidity);
});
document.addEventListener("DOMContentLoaded", () => document.querySelectorAll("[data-task-search]").forEach(syncTaskValidity));

// A date-time field with data-snap-minutes="<n>" (time rounding): the browser's picker offers every minute,
// so a picked or typed time snaps to the nearest step. The server rounds as well, see tracking/services.py.
document.addEventListener("change", (event) => {
  const field = event.target;
  const step = Number(field.dataset?.snapMinutes);
  if (!step || !field.value) return;
  const [date, time] = field.value.split("T");
  const [hours, minutes] = time.split(":").map(Number);
  const snapped = Math.round((hours * 60 + minutes) / step) * step;
  // Rounding up past midnight moves to the next day, like the server does.
  const day = new Date(`${date}T00:00`);
  day.setMinutes(snapped);
  const pad = (n) => String(n).padStart(2, "0");
  field.value = `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}T${pad(day.getHours())}:${pad(day.getMinutes())}`;
});
