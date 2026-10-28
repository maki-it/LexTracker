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
  box.className = "relative flex max-h-48 flex-col gap-1.5 overflow-y-auto rounded-lg border border-line px-3 py-2";
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
  // Scroll the chosen entry into view as soon as the list has a size, which is later when its fieldset is
  // hidden until the role is "customer".
  const chosen = entries.find(({ option }) => option.value && option.selected);
  if (chosen) {
    const observer = new ResizeObserver(() => {
      if (!box.clientHeight) return;
      box.scrollTop = chosen.label.offsetTop - header.offsetHeight - 8;
      observer.disconnect();
    });
    observer.observe(box);
  }
  select.hidden = true;
  select.before(box);
}
document.addEventListener("htmx:load", (event) => {
  event.detail.elt.querySelectorAll?.("select[data-searchable]").forEach(makeSearchable);
});
document.addEventListener("DOMContentLoaded", () => document.querySelectorAll("select[data-searchable]").forEach(makeSearchable));

// A button with data-open-dialog="<id>" opens that <dialog>, e.g. the menu behind the last tab of the bottom bar
// on phones. A tap beside the sheet closes it, and so does a link that opens the dialog of base.html.
document.addEventListener("click", (event) => {
  const opener = event.target.closest("[data-open-dialog]");
  if (opener) {
    document.getElementById(opener.dataset.openDialog).showModal();
    return;
  }
  const sheet = event.target.closest("dialog.sheet");
  if (!sheet) return;
  if (event.target === sheet) {
    const box = sheet.getBoundingClientRect();
    if (event.clientY < box.top || event.clientY > box.bottom) sheet.close();
  } else if (event.target.closest("a[hx-get]")) {
    sheet.close();
  }
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
  input.setCustomValidity(picked.value ? "" : search.dataset.invalidMessage);
}

function pickTask(search, option) {
  const { input, picked } = taskParts(search);
  picked.value = option.dataset.value;
  input.value = option.dataset.label;
  search.querySelector("[data-task-name]").textContent = option.dataset.name;
  search.querySelector("[data-task-sub]").textContent = option.dataset.sub;
  search.dataset.picked = "";
  delete search.dataset.editing;
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
  delete search.dataset.picked;
  syncTaskValidity(search);
});

// On phones a picked task shows as two lines (see .task-summary); a tap on it brings back the field to search again.
document.addEventListener("click", (event) => {
  const summary = event.target.closest("[data-task-summary]");
  const search = taskSearchOf(summary);
  if (!search) return;
  search.dataset.editing = "";
  taskParts(search).input.focus();
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
  if (!search || search.contains(event.relatedTarget)) return;
  showTaskResults(search, false);
  delete search.dataset.editing;
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

// The entry form (tracking/form.html) keeps start and end in two hidden fields. The day pills, the duration
// buttons and the two clocks all read and write them, so the controls never disagree. Times are local to the
// browser, like the old date-time fields were. The server rounds to the time-rounding interval on saving.
const pad2 = (n) => String(n).padStart(2, "0");
const toFieldValue = (d) =>
  `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}T${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
const clock = (d) => `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
const dateValue = (d) => toFieldValue(d).slice(0, 10);
const hoursMinutes = (minutes) => `${Math.floor(minutes / 60)}:${pad2(minutes % 60)}`;
const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const plusMinutes = (d, minutes) => {
  const moved = new Date(d);
  moved.setMinutes(moved.getMinutes() + minutes);
  return moved;
};
// The next multiple of `step` in direction `dir`, e.g. 58 -> 60 (+1) or 45 (-1) for a step of 15.
const stepValue = (value, dir, step) =>
  (dir > 0 ? Math.floor(value / step) + 1 : Math.ceil(value / step) - 1) * step;
const roundValue = (value, step) => Math.round(value / step) * step;

function entryTimes(form) {
  let end = new Date(form.elements.ended_at.value);
  if (Number.isNaN(end.getTime())) end = new Date();
  let start = new Date(form.elements.started_at.value);
  if (Number.isNaN(start.getTime())) start = plusMinutes(end, -60);
  return { start, end };
}

function setEntryTimes(form, start, end) {
  form.elements.started_at.value = toFieldValue(start);
  form.elements.ended_at.value = toFieldValue(end);
  renderEntryForm(form);
}

function dayLabel(form, day) {
  const today = startOfDay(new Date());
  const days = Math.round((startOfDay(day) - today) / 86400000);
  if (days === 0) return form.dataset.todayLabel;
  if (days === -1) return form.dataset.yesterdayLabel;
  const format = new Intl.DateTimeFormat(document.documentElement.lang, { weekday: "short", day: "numeric", month: "numeric" });
  return format.format(day);
}

function renderEntryForm(form) {
  const { start, end } = entryTimes(form);
  const minutes = Math.max(0, Math.round((end - start) / 60000));
  const label = dayLabel(form, start);
  const days = Math.round((startOfDay(start) - startOfDay(new Date())) / 86400000);
  const out = (name, text) => form.querySelectorAll(`[data-out="${name}"]`).forEach((el) => (el.textContent = text));
  out("duration", hoursMinutes(minutes));
  out("period", `${label}, ${clock(start)} – ${clock(end)}`);
  out("day", label);
  form.querySelectorAll('[data-out="next-day"]').forEach((el) => (el.hidden = dateValue(start) === dateValue(end)));

  form.querySelector('[data-day="today"]').classList.toggle("pill-active", days === 0);
  form.querySelector('[data-day="yesterday"]').classList.toggle("pill-active", days === -1);
  const other = form.querySelector("[data-day-other]");
  other.classList.toggle("pill-active", days !== 0 && days !== -1);
  other.textContent = days === 0 || days === -1 ? form.dataset.otherLabel : label;
  form.querySelector("[data-day-input]").value = dateValue(start);

  form.querySelectorAll("[data-mode-button]").forEach((button) =>
    button.setAttribute("aria-pressed", String(button.dataset.modeButton === form.dataset.mode)),
  );
  form.querySelectorAll("[data-panel]").forEach((panel) => (panel.hidden = panel.dataset.panel !== form.dataset.mode));
  // The clock being typed into keeps its text, otherwise the cursor would jump while typing.
  for (const [name, value] of [["start", start], ["end", end]]) {
    const input = form.querySelector(`[data-time="${name}"]`);
    if (input !== document.activeElement) input.value = clock(value);
  }
}

function renderEntryForms(root) {
  root.querySelectorAll?.("[data-entry-form]").forEach(renderEntryForm);
}
document.addEventListener("htmx:load", (event) => renderEntryForms(event.detail.elt));
document.addEventListener("DOMContentLoaded", () => renderEntryForms(document));

document.addEventListener("click", (event) => {
  const form = event.target.closest("[data-entry-form]");
  if (!form) return;
  const step = Number(form.dataset.step) || 15;
  const { start, end } = entryTimes(form);
  const duration = Math.round((end - start) / 60000);
  const pill = event.target.closest("[data-day]");
  const mode = event.target.closest("[data-mode-button]");
  const stepButton = event.target.closest("[data-duration-step]");
  const quick = event.target.closest("[data-duration-set]");
  const shift = event.target.closest("[data-shift]");
  const dayInput = event.target.closest("[data-day-input]");

  if (pill) {
    const day = startOfDay(new Date());
    if (pill.dataset.day === "yesterday") day.setDate(day.getDate() - 1);
    setEntryDay(form, day);
  } else if (mode) {
    form.dataset.mode = mode.dataset.modeButton;
    renderEntryForm(form);
  } else if (stepButton) {
    // The end stays, the start moves.
    const minutes = Math.min(1440, Math.max(step, stepValue(duration, Number(stepButton.dataset.durationStep), step)));
    setEntryTimes(form, plusMinutes(end, -minutes), end);
  } else if (quick) {
    setEntryTimes(form, plusMinutes(end, -Number(quick.dataset.durationSet)), end);
  } else if (shift) {
    const dir = Number(shift.dataset.dir);
    if (shift.dataset.shift === "start") {
      const minutes = stepValue(start.getHours() * 60 + start.getMinutes(), dir, step);
      const moved = new Date(start.getFullYear(), start.getMonth(), start.getDate(), 0, minutes);
      // The start stays at least a step before the end.
      setEntryTimes(form, moved <= plusMinutes(end, -step) ? moved : plusMinutes(end, -step), end);
    } else {
      const minutes = stepValue(end.getHours() * 60 + end.getMinutes(), dir, step);
      const moved = new Date(end.getFullYear(), end.getMonth(), end.getDate(), 0, minutes);
      setEntryTimes(form, start, moved >= plusMinutes(start, step) ? moved : plusMinutes(start, step));
    }
  } else if (dayInput) {
    // A tap on the invisible date field opens the picker; desktop browsers only do so on a click on its icon.
    try {
      dayInput.showPicker();
    } catch {
      // Not supported or not allowed here: the field still takes typed dates.
    }
  }
});

// Moves start and end to another day and keeps the clock times (and the length) as they are.
function setEntryDay(form, day) {
  const { start, end } = entryTimes(form);
  const days = Math.round((startOfDay(day) - startOfDay(start)) / 86400000);
  const movedStart = new Date(start);
  const movedEnd = new Date(end);
  movedStart.setDate(movedStart.getDate() + days);
  movedEnd.setDate(movedEnd.getDate() + days);
  setEntryTimes(form, movedStart, movedEnd);
}

document.addEventListener("change", (event) => {
  const form = event.target.closest?.("[data-entry-form]");
  if (!form) return;
  if (event.target.matches("[data-day-input]") && event.target.value) {
    const [year, month, day] = event.target.value.split("-").map(Number);
    setEntryDay(form, new Date(year, month - 1, day));
  } else if (event.target.matches("[data-time]") && event.target.value) {
    const { start, end } = entryTimes(form);
    const [hours, minutes] = event.target.value.split(":").map(Number);
    const isStart = event.target.dataset.time === "start";
    const moved = new Date((isStart ? start : end).getFullYear(), (isStart ? start : end).getMonth(), (isStart ? start : end).getDate(), hours, minutes);
    setEntryTimes(form, isStart ? moved : start, isStart ? end : moved);
  }
});

// A typed time snaps to the rounding step when the field loses focus (the server rounds as well, see
// tracking/services.py). Snapping while typing would overwrite the first digits.
document.addEventListener("focusout", (event) => {
  const form = event.target.closest?.("[data-entry-form]");
  const rounding = Number(form?.dataset.rounding);
  if (!rounding || !event.target.matches("[data-time]") || !event.target.value) return;
  const [hours, minutes] = event.target.value.split(":").map(Number);
  const snapped = roundValue(hours * 60 + minutes, rounding);
  event.target.value = `${pad2(Math.floor(snapped / 60) % 24)}:${pad2(snapped % 60)}`;
  event.target.dispatchEvent(new Event("change", { bubbles: true }));
});

// Passkeys (WebAuthn): sign in on the login page and add passkeys in the account settings, see
// accounts/passkey_views.py. The server sends its options with base64url text where the browser wants binary data,
// and the answer goes back the same way.
function b64urlToBytes(text) {
  const base64 = text.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(text.length / 4) * 4, "=");
  return Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
}

function bytesToB64url(buffer) {
  let binary = "";
  for (const byte of new Uint8Array(buffer)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

const withBinaryIds = (list) => (list ?? []).map((item) => ({ ...item, id: b64urlToBytes(item.id) }));

async function postJson(url, body) {
  const token = document.querySelector("[name=csrfmiddlewaretoken]")?.value ?? "";
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRFToken": token },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error ?? "");
  return data;
}

// The prompt of the browser or the device was closed or timed out: nothing to report.
const passkeyCancelled = (error) => error.name === "NotAllowedError" || error.name === "AbortError";

// What only works with passkeys is hidden until the browser says it can do them.
function showPasskeyControls(root) {
  const supported = Boolean(window.PublicKeyCredential && navigator.credentials);
  root.querySelectorAll?.("[data-passkey-supported]").forEach((el) => (el.hidden = !supported));
  root.querySelectorAll?.("[data-passkey-unsupported]").forEach((el) => (el.hidden = supported));
  // A suggested name for the passkey that is added: this phone or this computer.
  const phone = window.matchMedia("(pointer: coarse)").matches;
  root.querySelectorAll?.("[data-passkey-name]").forEach((input) => {
    if (!input.value) input.value = phone ? input.dataset.namePhone : input.dataset.nameComputer;
  });
}
document.addEventListener("htmx:load", (event) => showPasskeyControls(event.detail.elt));
document.addEventListener("DOMContentLoaded", () => showPasskeyControls(document));

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-passkey-login]");
  if (!button) return;
  const error = document.querySelector("[data-passkey-error]");
  error.hidden = true;
  button.disabled = true;
  try {
    const options = await postJson(button.dataset.optionsUrl, {});
    const credential = await navigator.credentials.get({
      publicKey: { ...options, challenge: b64urlToBytes(options.challenge), allowCredentials: withBinaryIds(options.allowCredentials) },
    });
    const response = credential.response;
    const result = await postJson(button.dataset.loginUrl, {
      next: button.dataset.next,
      credential: {
        id: credential.id,
        rawId: bytesToB64url(credential.rawId),
        type: credential.type,
        authenticatorAttachment: credential.authenticatorAttachment,
        clientExtensionResults: credential.getClientExtensionResults(),
        response: {
          clientDataJSON: bytesToB64url(response.clientDataJSON),
          authenticatorData: bytesToB64url(response.authenticatorData),
          signature: bytesToB64url(response.signature),
          userHandle: response.userHandle ? bytesToB64url(response.userHandle) : null,
        },
      },
    });
    window.location.assign(result.redirect);
  } catch (failure) {
    if (!passkeyCancelled(failure)) {
      error.textContent = failure.message || button.dataset.errorText;
      error.hidden = false;
    }
    button.disabled = false;
  }
});

document.addEventListener("submit", async (event) => {
  const form = event.target.closest("[data-passkey-register]");
  if (!form) return;
  event.preventDefault();
  const error = form.querySelector("[data-passkey-error]");
  const button = form.querySelector("button[type=submit]");
  error.hidden = true;
  button.disabled = true;
  try {
    const options = await postJson(form.dataset.optionsUrl, {});
    const credential = await navigator.credentials.create({
      publicKey: {
        ...options,
        challenge: b64urlToBytes(options.challenge),
        user: { ...options.user, id: b64urlToBytes(options.user.id) },
        excludeCredentials: withBinaryIds(options.excludeCredentials),
      },
    });
    const response = credential.response;
    const result = await postJson(form.action, {
      name: form.elements.name.value,
      credential: {
        id: credential.id,
        rawId: bytesToB64url(credential.rawId),
        type: credential.type,
        authenticatorAttachment: credential.authenticatorAttachment,
        clientExtensionResults: credential.getClientExtensionResults(),
        response: {
          clientDataJSON: bytesToB64url(response.clientDataJSON),
          attestationObject: bytesToB64url(response.attestationObject),
          transports: response.getTransports?.() ?? [],
        },
      },
    });
    window.location.assign(result.redirect);
  } catch (failure) {
    if (failure.name === "InvalidStateError") {
      // The device already has a passkey for this account (see excludeCredentials on the server).
      error.textContent = form.dataset.alreadyText;
      error.hidden = false;
    } else if (!passkeyCancelled(failure)) {
      error.textContent = failure.message || form.dataset.errorText;
      error.hidden = false;
    }
    button.disabled = false;
  }
});

// Push notifications: this browser subscribes through the service worker (push/sw.js) and the server keeps the
// subscription (push/views.py). The server renders the list of devices; the script finds out which one is this
// browser and sets up the button that adds it.
const pushSupported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

async function pushSubscription() {
  const registration = await navigator.serviceWorker.getRegistration("/");
  return registration ? registration.pushManager.getSubscription() : null;
}

async function sha256Hex(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

// The browser may refuse storage (private window), the device then simply stays folded.
function pushOpenedKey() {
  try {
    return sessionStorage.getItem("pushOpen");
  } catch {
    return null;
  }
}

async function showPushState(root) {
  const section = root.querySelector?.("[data-push]");
  if (!section) return;
  const show = (name, visible = true) => section.querySelectorAll(`[data-push-${name}]`).forEach((el) => (el.hidden = !visible));
  if (!pushSupported()) {
    // iOS only has push for an app on the home screen, and then everything above exists.
    const ios = /iPhone|iPad/.test(navigator.userAgent) && !navigator.standalone;
    show(ios ? "ios" : "unsupported");
    return;
  }
  const subscription = await pushSubscription();
  const known = subscription ? await sha256Hex(subscription.endpoint) : "";
  let listed = false;
  for (const device of section.querySelectorAll("[data-push-device]")) {
    const here = known !== "" && device.dataset.endpointHash === known;
    listed ||= here;
    device.querySelector("[data-push-this]").hidden = !here;
    // The device that was just added shows its settings right away, the others stay folded.
    if (here && pushOpenedKey() === known) device.querySelector("details").open = true;
  }
  try {
    sessionStorage.removeItem("pushOpen");
  } catch {}
  show("active", listed);
  show("enable", !listed);
}
document.addEventListener("htmx:load", (event) => showPushState(event.target));
document.addEventListener("DOMContentLoaded", () => showPushState(document));

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-push-enable]");
  if (!button) return;
  const section = button.closest("[data-push]");
  const error = section.querySelector("[data-push-error]");
  error.hidden = true;
  button.disabled = true;
  try {
    // The permission has to be asked for in reaction to a tap, or iOS and Firefox refuse.
    if ((await Notification.requestPermission()) !== "granted") throw new Error(section.dataset.deniedText);
    const { key } = await (await fetch(section.dataset.keyUrl)).json();
    const serverKey = b64urlToBytes(key);
    await navigator.serviceWorker.register(section.dataset.scriptUrl, { scope: "/" });
    const registration = await navigator.serviceWorker.ready;
    let subscription = await registration.pushManager.getSubscription();
    // A subscription for another key (the server made a new one) cannot be used anymore.
    if (subscription && bytesToB64url(subscription.options.applicationServerKey) !== key) {
      await subscription.unsubscribe();
      subscription = null;
    }
    subscription ||= await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: serverKey });
    const phone = window.matchMedia("(pointer: coarse)").matches;
    const { endpoint, keys } = subscription.toJSON();
    try {
      sessionStorage.setItem("pushOpen", await sha256Hex(endpoint));
    } catch {}
    await postJson(section.dataset.subscribeUrl, {
      endpoint,
      keys,
      name: phone ? section.dataset.namePhone : section.dataset.nameComputer,
    });
    // In the dialog only its content is loaded again, a reload of the page behind it would close it.
    if (section.closest("#dialog-body")) {
      htmx.ajax("GET", section.dataset.returnUrl, { target: "#dialog-body", swap: "innerHTML" });
    } else {
      window.location.reload();
    }
  } catch (failure) {
    // Brave switches the push service of the browser off, and the browser then refuses with this message.
    const refused = /push service/i.test(failure.message);
    error.textContent = refused ? section.dataset.serviceText : failure.message || section.dataset.errorText;
    error.hidden = false;
    button.disabled = false;
  }
});

// Removing the device that this browser is: the browser's subscription goes with it.
document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-push-remove]");
  // A "no" in the confirmation has cancelled the click already.
  if (!button || event.defaultPrevented || button.dataset.done) return;
  event.preventDefault();
  try {
    const subscription = pushSupported() ? await pushSubscription() : null;
    const device = button.closest("[data-push-device]");
    if (subscription && device.dataset.endpointHash === (await sha256Hex(subscription.endpoint))) {
      await subscription.unsubscribe();
    }
  } finally {
    button.dataset.done = "1";
    button.form.requestSubmit(button);
  }
});

// A <select data-autosubmit> sends its form as soon as another entry is picked, e.g. the language on the login page.
document.addEventListener("change", (event) => {
  if (event.target.matches?.("[data-autosubmit]")) event.target.form.requestSubmit();
});

// A button with data-popover-toggle="<id>" shows or hides the element with that id, e.g. the week picker.
// A click outside of it (or on its backdrop, the element itself), a click on another toggle, or Escape closes it.
function setPopover(button, open) {
  button.setAttribute("aria-expanded", open);
  document.getElementById(button.dataset.popoverToggle).hidden = !open;
}
document.addEventListener("click", (event) => {
  const toggle = event.target.closest("[data-popover-toggle]");
  for (const button of document.querySelectorAll("[data-popover-toggle][aria-expanded=true]")) {
    const popover = document.getElementById(button.dataset.popoverToggle);
    if (button !== toggle && (event.target === popover || !popover.contains(event.target))) setPopover(button, false);
  }
  if (toggle) setPopover(toggle, toggle.getAttribute("aria-expanded") !== "true");
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  for (const button of document.querySelectorAll("[data-popover-toggle][aria-expanded=true]")) {
    setPopover(button, false);
    button.focus();
  }
});

// Browsers without Speculation Rules (Brave, Firefox, Safari) do not read the rule in base.html. They get the same
// effect here: a navigation link is fetched in the background once the mouse rests on it for 100 ms or a finger touches it.
if (!(window.HTMLScriptElement && HTMLScriptElement.supports && HTMLScriptElement.supports("speculationrules"))) {
  const NAV_LINKS = "#sidebar-nav a, .bottom-bar a";
  const prefetched = new Set();
  let hoverTimer;

  const prefetch = (link) => {
    if (link.origin !== location.origin || link.href === location.href || prefetched.has(link.href)) return;
    prefetched.add(link.href);
    const hint = document.createElement("link");
    hint.rel = "prefetch";
    hint.as = "document";
    hint.href = link.href;
    document.head.append(hint);
  };

  document.addEventListener("mouseover", (event) => {
    const link = event.target.closest?.(NAV_LINKS);
    clearTimeout(hoverTimer);
    if (link) hoverTimer = setTimeout(() => prefetch(link), 100);
  });
  document.addEventListener("mouseout", () => clearTimeout(hoverTimer));
  document.addEventListener(
    "touchstart",
    (event) => {
      const link = event.target.closest?.(NAV_LINKS);
      if (link) prefetch(link);
    },
    { passive: true },
  );
}

// Markdown editor (core/forms.py MarkdownTextarea, templates/core/_markdown_editor.html): buttons above the text
// field, a tab with the preview (rendered by the server, so it looks like the saved text) and a few shortcuts.
// Edits go through insertText where the browser allows it, so Strg+Z undoes them.
const MD_URL = /^(https?:\/\/|www\.)\S+$/i;
// What a list item starts with: "- ", "- [ ] " or "1. ".
const MD_LIST_PREFIX = /^(?:[-*] (?:\[[ xX]\] )?|\d+\. )/;

function mdReplace(input, start, end, text, selectStart = start + text.length, selectEnd = selectStart) {
  input.focus();
  input.setSelectionRange(start, end);
  const done = text ? document.execCommand("insertText", false, text) : document.execCommand("delete");
  if (!done) {
    input.setRangeText(text, start, end, "end");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }
  input.setSelectionRange(selectStart, selectEnd);
}

// **bold**, *italic*, `code`: wraps the selection, or takes the marks away when they are already there.
function mdWrap(input, before, after, placeholder) {
  const { selectionStart: start, selectionEnd: end, value } = input;
  const selected = value.slice(start, end);
  if (value.slice(start - before.length, start) === before && value.slice(end, end + after.length) === after) {
    mdReplace(input, start - before.length, end + after.length, selected, start - before.length, start - before.length + selected.length);
  } else if (selected.length >= before.length + after.length && selected.startsWith(before) && selected.endsWith(after)) {
    const inner = selected.slice(before.length, selected.length - after.length);
    mdReplace(input, start, end, inner, start, start + inner.length);
  } else {
    const text = selected || placeholder;
    mdReplace(input, start, end, before + text + after, start + before.length, start + before.length + text.length);
  }
}

// A prefix in front of every selected line (heading, quote, lists). It is taken away again when all of them have
// it (`own`). Otherwise another prefix of the same kind (`strip`) is replaced, e.g. "- " by "1. ".
function mdLines(input, prefixOf, own, strip) {
  const { value } = input;
  const start = value.lastIndexOf("\n", input.selectionStart - 1) + 1;
  const found = value.indexOf("\n", input.selectionEnd);
  const end = found === -1 ? value.length : found;
  const lines = value.slice(start, end).split("\n");
  const remove = lines.every((line) => own.test(line));
  const text = lines.map((line, i) => (remove ? line.replace(own, "") : prefixOf(i) + line.replace(strip, ""))).join("\n");
  if (input.selectionStart === input.selectionEnd) {
    // Nothing selected: the cursor stays where it was in the line.
    const caret = Math.max(start, input.selectionStart + text.length - (end - start));
    mdReplace(input, start, end, text, caret);
  } else {
    mdReplace(input, start, end, text, start, start + text.length);
  }
}

function mdLink(input, placeholder) {
  const { selectionStart: start, selectionEnd: end, value } = input;
  const selected = value.slice(start, end);
  if (MD_URL.test(selected)) {
    // A URL is selected: it becomes the address, the cursor waits for the text.
    mdReplace(input, start, end, `[](${selected})`, start + 1);
  } else {
    const text = selected || placeholder;
    const urlStart = start + text.length + 3;
    mdReplace(input, start, end, `[${text}](url)`, urlStart, urlStart + 3);
  }
}

const MD_TOOLS = {
  heading: (input) => mdLines(input, () => "### ", /^#{1,6} /, /^#{1,6} /),
  bold: (input, placeholder) => mdWrap(input, "**", "**", placeholder),
  italic: (input, placeholder) => mdWrap(input, "*", "*", placeholder),
  quote: (input) => mdLines(input, () => "> ", /^> ?/, /^> ?/),
  code: (input, placeholder) => {
    const multiline = input.value.slice(input.selectionStart, input.selectionEnd).includes("\n");
    if (multiline) mdWrap(input, "```\n", "\n```", placeholder);
    else mdWrap(input, "`", "`", placeholder);
  },
  link: mdLink,
  list: (input) => mdLines(input, () => "- ", /^[-*] (?!\[[ xX]\] )/, MD_LIST_PREFIX),
  ordered: (input) => mdLines(input, (i) => `${i + 1}. `, /^\d+\. /, MD_LIST_PREFIX),
  task: (input) => mdLines(input, () => "- [ ] ", /^[-*] \[[ xX]\] /, MD_LIST_PREFIX),
};

// The text a tool puts in when nothing is selected comes with its button (data-md-placeholder), in the user's language.
function mdRun(input, name) {
  const button = input.closest("[data-md-editor]").querySelector(`[data-md-tool="${name}"]`);
  MD_TOOLS[name](input, button.dataset.mdPlaceholder);
}

// The buttons keep the focus (and so the selection) in the text field.
document.addEventListener("mousedown", (event) => {
  if (event.target.closest("[data-md-tool]")) event.preventDefault();
});

document.addEventListener("click", (event) => {
  const tool = event.target.closest("[data-md-tool]");
  if (tool) {
    mdRun(tool.closest("[data-md-editor]").querySelector("[data-md-input]"), tool.dataset.mdTool);
    return;
  }
  const tab = event.target.closest("[data-md-tab]");
  if (!tab) return;
  const editor = tab.closest("[data-md-editor]");
  const input = editor.querySelector("[data-md-input]");
  const preview = editor.querySelector(".md-preview");
  const showPreview = tab.dataset.mdTab === "preview";
  for (const other of editor.querySelectorAll("[data-md-tab]")) {
    other.classList.toggle("md-tab-active", other === tab);
    other.setAttribute("aria-selected", other === tab);
  }
  editor.querySelector(".md-tools").hidden = showPreview;
  if (showPreview) {
    // As high as the field was, so the dialog does not jump.
    preview.style.minHeight = `${input.offsetHeight}px`;
    preview.textContent = "";
    htmx.ajax("POST", tab.dataset.mdPreviewUrl, { target: preview, swap: "innerHTML", values: { text: input.value } });
  }
  input.hidden = showPreview;
  preview.hidden = !showPreview;
  if (!showPreview) input.focus();
});

document.addEventListener("keydown", (event) => {
  const input = event.target.closest?.("[data-md-input]");
  if (!input || event.isComposing) return;
  const key = event.key.toLowerCase();
  if ((event.ctrlKey || event.metaKey) && !event.shiftKey && !event.altKey) {
    const tool = { b: "bold", i: "italic", k: "link" }[key];
    if (tool) {
      event.preventDefault();
      mdRun(input, tool);
    }
    return;
  }
  // Enter at the end of a list item starts the next item. On an empty item it ends the list instead.
  if (key !== "enter" || event.shiftKey || event.ctrlKey || event.metaKey || input.selectionStart !== input.selectionEnd) return;
  const caret = input.selectionStart;
  const lineStart = input.value.lastIndexOf("\n", caret - 1) + 1;
  const atEnd = input.value.slice(caret).split("\n", 1)[0] === "";
  const item = input.value.slice(lineStart, caret).match(/^(\s*)(?:([-*]) (\[[ xX]\] )?|(\d+)\. )(.*)$/);
  if (!item || !atEnd) return;
  event.preventDefault();
  if (item[5] === "") {
    mdReplace(input, lineStart, caret, "", lineStart);
    return;
  }
  const marker = item[4] ? `${Number(item[4]) + 1}. ` : `${item[2]} ${item[3] ? "[ ] " : ""}`;
  mdReplace(input, caret, caret, `\n${item[1]}${marker}`);
});

// A URL pasted over selected text turns the text into a link: [text](url).
document.addEventListener("paste", (event) => {
  const input = event.target.closest?.("[data-md-input]");
  const url = event.clipboardData?.getData("text/plain").trim();
  if (!input || !url || !MD_URL.test(url)) return;
  const { selectionStart: start, selectionEnd: end, value } = input;
  const selected = value.slice(start, end);
  if (start === end || selected.includes("\n") || MD_URL.test(selected)) return;
  event.preventDefault();
  mdReplace(input, start, end, `[${selected}](${url.startsWith("www.") ? `https://${url}` : url})`);
});
