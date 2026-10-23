"""Render the Markdown that users write in descriptions and notes."""

from django import template
from django.utils.safestring import mark_safe
from markdown_it import MarkdownIt

register = template.Library()

# Only the small part of Markdown that descriptions need: paragraphs, lists, line breaks,
# **bold**, *italic*, ~~struck~~, `code` and links. Raw HTML stays text ("html": False), and
# markdown-it drops links to javascript:, vbscript:, file: and data: URLs.
_md = MarkdownIt("zero", {"html": False, "breaks": True}).enable(
    ["list", "newline", "escape", "backticks", "emphasis", "strikethrough", "link", "autolink", "entity"]
)


def _render_link_open(renderer, tokens, idx, options, env):
    tokens[idx].attrSet("target", "_blank")
    tokens[idx].attrSet("rel", "noopener noreferrer")
    return renderer.renderToken(tokens, idx, options, env)


_md.add_render_rule("link_open", _render_link_open)


@register.filter
def markdown(value: str | None) -> str:
    """``{{ project.description|markdown }}``: the text as HTML, wrapped in ``<div class="markdown">``."""
    if not value:
        return ""
    return mark_safe(f'<div class="markdown">{_md.render(value)}</div>')  # markdown-it escapes the text
