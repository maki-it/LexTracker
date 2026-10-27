import json
import re

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

RULES = re.compile(r'<script type="speculationrules">(.*?)</script>', re.DOTALL)


def test_pages_prefetch_the_navigation_links_on_hover_or_touch(client, user):
    client.force_login(user)

    html = client.get(reverse("core:dashboard")).text

    (rules,) = RULES.findall(html)
    # Only the navigation (sidebar and phone bottom bar): other links could trigger exports or heavy requests.
    assert json.loads(rules) == {
        "prefetch": [{"where": {"selector_matches": "#sidebar-nav a, .bottom-bar a"}, "eagerness": "moderate"}]
    }
    assert 'id="sidebar-nav"' in html
    assert 'class="bottom-bar"' in html


def test_login_page_has_nothing_to_prefetch(client, user):
    assert not RULES.findall(client.get(reverse("accounts:login")).text)
