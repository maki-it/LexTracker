import json
import re

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

RULES = re.compile(r'<script type="speculationrules">(.*?)</script>', re.DOTALL)


def test_pages_prefetch_the_sidebar_links_on_touch(client, user):
    client.force_login(user)

    html = client.get(reverse("core:dashboard")).text

    (rules,) = RULES.findall(html)
    # Only the navigation: prefetching other links could trigger exports or other heavy requests.
    assert json.loads(rules) == {
        "prefetch": [{"where": {"selector_matches": "#sidebar-nav a"}, "eagerness": "conservative"}]
    }
    assert 'id="sidebar-nav"' in html


def test_login_page_has_nothing_to_prefetch(client, user):
    assert not RULES.findall(client.get(reverse("accounts:login")).text)
