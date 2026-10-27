from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

PHONE_PATH = (
    "M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3"
    "a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4"
    "c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"
)

# Inner SVG markup of 24x24 stroke icons (in the style of Lucide).
ICONS = {
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/>'
    '<rect x="14" y="12" width="7" height="9" rx="1"/>'
    '<rect x="3" y="16" width="7" height="5" rx="1"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "tasks": '<path d="m3.5 6 1.5 1.5L8 4.5"/><path d="m3.5 12 1.5 1.5 3-3"/><path d="m3.5 18 1.5 1.5 3-3"/>'
    '<path d="M12 6h9M12 12h9M12 18h9"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/>'
    '<path d="M16 4.5a3.5 3.5 0 0 1 0 7"/><path d="M18 14.5a6.5 6.5 0 0 1 3.5 5.5"/>',
    "user-cog": (
        '<circle cx="10" cy="8" r="4"/><path d="M3 21a7 7 0 0 1 11-5.7"/><circle cx="18" cy="17" r="2.5"/>'
        '<path d="M18 13v1.5M18 19.5V21M14.5 17H16M20 17h1.5"/>'
    ),
    "building": '<rect x="5" y="3" width="14" height="18" rx="1"/>'
    '<path d="M9 7h2M13 7h2M9 11h2M13 11h2M10 21v-4h4v4"/>',
    "receipt": '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/>',
    "settings": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/>'
    '<circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
    "play": '<path d="M7 4.5v15l12-7.5z"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "pencil": '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
    "chart": '<path d="M4 20V10M10 20V4M16 20v-7M21 20H3"/>',
    "archive": '<rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v11h14V8"/><path d="M10 12h4"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "chevron-left": '<path d="m15 18-6-6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "download": '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
    "upload": '<path d="M12 15V3"/><path d="m7 8 5-5 5 5"/><path d="M5 21h14"/>',
    "external": '<path d="M14 4h6v6"/><path d="M20 4 10 14"/>'
    '<path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.5-4.5L4 8"/><path d="M4 3v5h5"/>'
    '<path d="M4 13a8 8 0 0 0 14.5 4.5L20 16"/><path d="M20 21v-5h-5"/>',
    "shield": '<path d="M12 3 4 6v6c0 4.5 3.4 8.3 8 9 4.6-.7 8-4.5 8-9V6z"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    "phone": f'<path d="{PHONE_PATH}"/>',
    "key": '<circle cx="8" cy="15" r="4.5"/><path d="m11.5 11.5 9-9"/><path d="m17 6 3 3"/>',
    "mail": '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/>',
    "map-pin": '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/>',
    # The Markdown editor's buttons (templates/core/_markdown_editor.html).
    "heading": '<path d="M6 12h12"/><path d="M6 20V4"/><path d="M18 20V4"/>',
    "bold": '<path d="M6 12h9a4 4 0 0 1 0 8H7a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h7a4 4 0 0 1 0 8"/>',
    "italic": '<path d="M19 4h-9"/><path d="M14 20H5"/><path d="M15 4 9 20"/>',
    "quote": '<path d="M3 21c3 0 7-1 7-8V5c0-1.2-.8-2-2-2H4c-1.2 0-2 .8-2 2v6c0 1.2.8 2 2 2h4"/>'
    '<path d="M15 21c3 0 7-1 7-8V5c0-1.2-.8-2-2-2h-4c-1.2 0-2 .8-2 2v6c0 1.2.8 2 2 2h4"/>',
    "code": '<path d="m16 18 6-6-6-6"/><path d="m8 6-6 6 6 6"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
    '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    "list": '<path d="M3 6h.01M3 12h.01M3 18h.01"/><path d="M8 6h13M8 12h13M8 18h13"/>',
    "list-ordered": '<path d="M11 5h10M11 12h10M11 19h10"/><path d="M4 4h1v5"/><path d="M4 9h2"/>'
    '<path d="M6.5 20H3.4c0-1 2.6-1.9 2.6-3.5a1.5 1.5 0 0 0-2.6-1"/>',
    "list-checks": '<path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/><path d="M13 6h8M13 12h8M13 18h8"/>',
    "trash": '<path d="M4 7h16"/><path d="M10 11v6M14 11v6"/><path d="M6 7l1 13h10l1-13"/><path d="M9 7V4h6v3"/>',
}


@register.simple_tag
def icon(name: str, size: int = 16, css_class: str = "") -> str:
    """Inline SVG icon, coloured with the current text colour and hidden from screen readers."""
    return format_html(
        '<svg aria-hidden="true" class="{}" width="{}" height="{}" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{}</svg>',
        f"shrink-0 {css_class}".strip(),
        size,
        size,
        mark_safe(ICONS[name]),  # static markup from the dict above
    )


# The LexTracker mark: a clock whose hands form an "L". Same drawing as static/img/favicon.svg.
LOGO = (
    '<rect width="32" height="32" rx="8" fill="#4f46e5"/>'
    '<circle cx="16" cy="16" r="10" fill="none" stroke="#fff" stroke-opacity=".35" stroke-width="2.4"/>'
    '<path d="M16 9.5V16h5.5" fill="none" stroke="#fff" stroke-width="3" '
    'stroke-linecap="round" stroke-linejoin="round"/>'
)


@register.simple_tag(takes_context=True)
def logo(context, size: int = 28) -> str:
    """The uploaded logo, or the built-in mark, hidden from screen readers (the name stands next to it)."""
    brand = context.get("brand")
    if brand and brand.logo_url:
        return format_html(
            '<img src="{}" alt="" class="shrink-0 rounded-md object-contain" width="{}" height="{}">',
            brand.logo_url,
            size,
            size,
        )
    return format_html(
        '<svg aria-hidden="true" class="shrink-0" width="{}" height="{}" viewBox="0 0 32 32">{}</svg>',
        size,
        size,
        mark_safe(LOGO),  # static markup from above
    )
