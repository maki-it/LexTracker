"""Markdown in descriptions and notes: rendering them as HTML, and ticking a checklist item in the text."""

import re
from html import escape

from django.utils.safestring import SafeString, mark_safe
from markdown_it import MarkdownIt
from markdown_it.rules_core import StateCore
from markdown_it.token import Token

# Only the part of Markdown that descriptions need: paragraphs, headings, quotes, code, lists with checklists,
# line breaks, **bold**, *italic*, ~~struck~~, `code` and links (also bare URLs). Raw HTML stays text ("html": False),
# and markdown-it drops links to javascript:, vbscript:, file: and data: URLs.
_md = MarkdownIt("zero", {"html": False, "breaks": True, "linkify": True}).enable(
    [
        "heading",
        "blockquote",
        "fence",
        "list",
        "newline",
        "escape",
        "backticks",
        "emphasis",
        "strikethrough",
        "link",
        "autolink",
        "linkify",
        "entity",
    ]
)
# Only addresses with a scheme or "www." become links. "datei.py" or "Ende.Nein" are not domains, even if the
# ending is one (.py is Paraguay's).
_md.linkify.set({"fuzzy_link": False, "fuzzy_email": False})
_md.linkify.add(
    "www.",
    {
        # What follows "www.": the domain, and a path that does not end in the punctuation of the sentence.
        "validate": (
            r"[a-zA-Z0-9][a-zA-Z0-9-]*(?:\.[a-zA-Z0-9][a-zA-Z0-9-]*)+(?::\d+)?"
            r"(?:[/?#][^\s<>]*[^\s<>.,;:!?)\"'])?"
        ),
        "normalize": lambda _linkify, match: setattr(match, "url", f"https://{match.url}"),
    },
)

# "[ ] " or "[x] " at the start of a list item.
_TASK = re.compile(r"\[([ xX])\] ")
# The marker of a list item up to its checkbox, also inside quotes: "- [ ]", "1. [x]", "> * [ ]".
_TASK_LINE = re.compile(r"^([\s>]*(?:[-*+]|\d+[.)])\s+\[)[ xX](\])")


def _tasks(state: StateCore) -> None:
    """Turn "- [ ] text" into a list item with a checkbox, numbered in the order they appear in the text."""
    tokens = state.tokens
    index = 0
    i = 0
    while i < len(tokens) - 2:
        item, paragraph, inline = tokens[i : i + 3]
        i += 1
        if item.type != "list_item_open" or paragraph.type != "paragraph_open" or inline.type != "inline":
            continue
        match = _TASK.match(inline.content)
        if not match:
            continue
        inline.content = inline.content[match.end() :]
        item.attrJoin("class", "task")
        checkbox = Token("task_checkbox", "", 0)
        checkbox.meta = {"index": index, "checked": match[1] != " ", "line": item.map[0]}
        tokens.insert(i, checkbox)
        index += 1


_md.core.ruler.after("block", "tasks", _tasks)


def _render_link_open(renderer, tokens, idx, options, env):
    tokens[idx].attrSet("target", "_blank")
    tokens[idx].attrSet("rel", "noopener noreferrer")
    return renderer.renderToken(tokens, idx, options, env)


def _render_task_checkbox(renderer, tokens, idx, options, env):
    meta = tokens[idx].meta
    attrs = 'type="checkbox" class="task-checkbox"' + (" checked" if meta["checked"] else "")
    toggle_url = env.get("toggle_url")
    if not toggle_url:
        return f"<input {attrs} disabled>"
    # Ticking it saves the text and swaps in the new HTML, see core.views.markdown_toggle.
    return (
        f'<input {attrs} name="checked" value="1" hx-post="{escape(toggle_url)}" hx-trigger="change" '
        f'hx-target="closest .markdown" hx-swap="outerHTML" hx-disabled-elt="this" '
        f"""hx-vals='{{"index": {meta["index"]}}}'>"""
    )


_md.add_render_rule("link_open", _render_link_open)
_md.add_render_rule("task_checkbox", _render_task_checkbox)


def render(text: str | None, toggle_url: str | None = None, error: str = "") -> SafeString:
    """The text as HTML, wrapped in ``<div class="markdown">``.

    With a ``toggle_url``, the checkboxes of a checklist post their tick there; without, they are shown disabled.
    An ``error`` is shown below the text, e.g. why a tick could not be saved.
    """
    if not text:
        return mark_safe("")
    body = _md.render(text, {"toggle_url": toggle_url})
    note = f'<p class="text-xs text-danger">{escape(error)}</p>' if error else ""
    return mark_safe(f'<div class="markdown">{body}{note}</div>')  # markdown-it escapes the text


def set_task(text: str, index: int, checked: bool) -> str | None:
    """The text with the checklist item number ``index`` ticked or unticked, or None if there is no such item."""
    for token in _md.parse(text):
        if token.type == "task_checkbox" and token.meta["index"] == index:
            line = token.meta["line"]
            break
    else:
        return None
    # Keep the original line breaks: markdown-it counts "\r\n", "\r" and "\n" as one line break each.
    parts = re.split(r"(\r\n|\r|\n)", text)
    changed, count = _TASK_LINE.subn(lambda m: f"{m[1]}{'x' if checked else ' '}{m[2]}", parts[line * 2], count=1)
    if not count:
        return None
    parts[line * 2] = changed
    return "".join(parts)
