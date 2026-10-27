import json
import uuid

import httpx
import pytest
from django.urls import reverse

from accounts.models import User
from core.markdown import set_task
from core.templatetags.markdown import markdown
from customers.models import Customer
from projects.models import TaskTemplate
from reminders.models import Reminder
from tests.lexware_fakes import contact, fake_client

pytestmark = pytest.mark.django_db


def test_renders_links_bold_and_italic():
    html = markdown("[example.com](https://example.com) ist **fett** und *kursiv*")

    assert '<a href="https://example.com" target="_blank" rel="noopener noreferrer">example.com</a>' in html
    assert "<strong>fett</strong>" in html
    assert "<em>kursiv</em>" in html


def test_keeps_line_breaks_and_lists():
    html = markdown("Zeile 1\nZeile 2\n\n- eins\n- zwei")

    assert "Zeile 1<br>" in html
    assert "<li>eins</li>" in html


@pytest.mark.parametrize(
    "text",
    [
        "<script>alert(1)</script>",
        '<img src=x onerror="alert(1)">',
        "[klick](javascript:alert(1))",
        '[klick](https://example.com" onclick="alert(1))',
    ],
)
def test_never_outputs_raw_html_or_script_links(text):
    html = markdown(text)

    assert "<script" not in html
    assert "<img" not in html
    assert 'onclick="' not in html
    assert 'href="javascript' not in html


def test_renders_headings_quotes_and_code_blocks():
    html = markdown("# Titel\n\n> zitiert\n\n```\nx = 1\n```")

    assert "<h1>Titel</h1>" in html
    assert "<blockquote>" in html
    assert "<pre><code>x = 1\n</code></pre>" in html


def test_a_hash_without_space_is_not_a_heading():
    assert "<h1" not in markdown("#kein-titel")


def test_bare_urls_become_links():
    html = markdown("Siehe https://example.com/a?b=1, auch www.example.org.")

    assert '<a href="https://example.com/a?b=1" target="_blank" rel="noopener noreferrer">' in html
    assert '<a href="https://www.example.org" target="_blank" rel="noopener noreferrer">www.example.org</a>.' in html


def test_text_that_only_looks_like_a_domain_stays_text():
    assert "<a " not in markdown("Datei main.py und Ende.Nein, mail@example.com")


def test_urls_in_code_and_links_are_not_linked_twice():
    html = markdown("`https://example.com` und [Seite](https://example.com)")

    assert html.count("<a ") == 1
    assert "<code>https://example.com</code>" in html


def test_checklists_are_read_only_without_an_address():
    html = markdown("- [ ] offen\n- [x] erledigt")

    assert html.count("<input") == 2
    assert html.count("disabled") == 2
    assert html.count("checked") == 1
    assert "hx-post" not in html
    assert '<li class="task">' in html


def test_checklists_in_code_blocks_are_text():
    assert "<input" not in markdown("```\n- [ ] kein Punkt\n```")


def test_a_bracket_without_a_list_is_text():
    assert "<input" not in markdown("[ ] kein Listenpunkt")


@pytest.mark.parametrize(
    ("text", "index", "checked", "expected"),
    [
        ("- [ ] a\n- [ ] b", 1, True, "- [ ] a\n- [x] b"),
        ("- [x] a\n- [x] b", 0, False, "- [ ] a\n- [x] b"),
        ("* [ ] a", 0, True, "* [x] a"),
        ("1. [ ] a\n2. [ ] b", 1, True, "1. [ ] a\n2. [x] b"),
        ("  - [ ] eingerückt", 0, True, "  - [x] eingerückt"),
        ("> - [ ] im Zitat", 0, True, "> - [x] im Zitat"),
        # Not counted: checklists in code, and "[ ]" that is not at the start of an item.
        ("```\n- [ ] Code\n```\n- [ ] echt", 0, True, "```\n- [ ] Code\n```\n- [x] echt"),
        ("- [ ] a\n- noch [ ] b\n- [ ] c", 1, True, "- [ ] a\n- noch [ ] b\n- [x] c"),
        # Line breaks of a browser form stay as they are.
        ("Text\r\n\r\n- [ ] a\r\n- [ ] b\r\n", 1, True, "Text\r\n\r\n- [ ] a\r\n- [x] b\r\n"),
    ],
)
def test_set_task_changes_only_that_item(text, index, checked, expected):
    assert set_task(text, index, checked) == expected


def test_set_task_without_such_an_item():
    assert set_task("- [ ] a", 1, True) is None
    assert set_task("kein Punkt", 0, True) is None


def test_empty_text_renders_nothing():
    assert markdown("") == ""
    assert markdown(None) == ""


def test_project_page_renders_description(client, user, task):
    client.force_login(user)
    task.project.description = "Siehe **Angebot** auf [example.com](https://example.com)"
    task.project.save()
    task.description = "Nur *Startseite*"
    task.save()

    response = client.get(reverse("projects:detail", args=[task.project.pk]))

    assert "<strong>Angebot</strong>" in response.text
    assert 'href="https://example.com"' in response.text
    assert "<em>Startseite</em>" in response.text


def test_customer_list_renders_notes(client, user):
    client.force_login(user)
    Customer.objects.create(name="ACME GmbH", notes="**Wichtig** <b>roh</b>")

    response = client.get(reverse("customers:list"))

    assert "<strong>Wichtig</strong>" in response.text
    assert "&lt;b&gt;roh&lt;/b&gt;" in response.text


@pytest.fixture
def project(task):
    task.project.description = "Ablauf:\n- [ ] Angebot\n- [ ] Vertrag"
    task.project.save()
    return task.project


def toggle(client, target, pk, index, checked=True):
    data = {"index": index} | ({"checked": "1"} if checked else {})
    return client.post(reverse("core:markdown_toggle", args=[target, pk]), data)


def test_pages_show_checklists_that_can_be_ticked(client, user, project):
    client.force_login(user)

    response = client.get(reverse("projects:detail", args=[project.pk]))

    url = reverse("core:markdown_toggle", args=["project", project.pk])
    assert response.text.count(f'hx-post="{url}"') == 2
    assert "hx-vals='{\"index\": 1}'" in response.text


def test_ticking_saves_the_text_and_answers_with_the_new_html(client, user, project):
    client.force_login(user)

    response = toggle(client, "project", project.pk, 1)

    assert response.status_code == 200
    assert response.text.count(" checked") == 1
    project.refresh_from_db()
    assert project.description == "Ablauf:\n- [ ] Angebot\n- [x] Vertrag"

    toggle(client, "project", project.pk, 1, checked=False)

    project.refresh_from_db()
    assert project.description == "Ablauf:\n- [ ] Angebot\n- [ ] Vertrag"


def test_ticking_works_for_every_kind_of_text(client, user, task):
    client.force_login(user)
    texts = [
        ("task", task, "description"),
        ("customer", task.project.customer, "notes"),
        ("task-template", TaskTemplate.objects.create(name="Vorlage"), "description"),
        ("reminder", Reminder.objects.create(title="Anrufen", user=user, customer=task.project.customer), "notes"),
    ]
    for target, obj, field in texts:
        setattr(obj, field, "- [ ] a")
        obj.save()

        assert toggle(client, target, obj.pk, 0).status_code == 200
        obj.refresh_from_db()
        assert getattr(obj, field) == "- [x] a"


def test_ticking_an_item_that_is_gone_shows_a_note_and_keeps_the_text(client, user, project):
    client.force_login(user)

    response = toggle(client, "project", project.pk, 5)

    assert "Lade die Seite neu" in response.text
    project.refresh_from_db()
    assert project.description == "Ablauf:\n- [ ] Angebot\n- [ ] Vertrag"


def test_ticking_needs_an_index(client, user, project):
    client.force_login(user)

    response = client.post(reverse("core:markdown_toggle", args=["project", project.pk]), {"index": "x"})

    assert response.status_code == 400


def test_ticking_is_for_administrators(client, project):
    mia = User.objects.create_user(username="mia", password="geheim-123", role=User.Role.EMPLOYEE)
    client.force_login(mia)

    assert toggle(client, "project", project.pk, 0).status_code == 403
    project.refresh_from_db()
    assert "[x]" not in project.description


def test_ticking_an_unknown_text_or_one_of_another_users_reminder_is_not_found(client, user, project):
    other = User.objects.create_user(username="mia", password="geheim-123", role=User.Role.ADMIN)
    reminder = Reminder.objects.create(title="Privat", user=other, customer=project.customer, notes="- [ ] a")
    client.force_login(user)

    assert toggle(client, "invoice", project.pk, 0).status_code == 404
    assert toggle(client, "reminder", reminder.pk, 0).status_code == 404
    reminder.refresh_from_db()
    assert reminder.notes == "- [ ] a"


def test_ticking_a_note_of_a_lexware_customer_sends_it_to_lexware(client, user, monkeypatch, settings):
    settings.LEXWARE_API_KEY = "test-key"
    raw = contact("ACME GmbH", version=4)
    customer = Customer.objects.create(
        name="ACME GmbH", lexware_id=uuid.UUID(raw["id"]), lexware_version=4, notes="- [ ] a", lexware_note="- [ ] a"
    )
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PUT":
            return httpx.Response(200, json={"id": raw["id"], "version": 5})
        return httpx.Response(200, json=raw)

    monkeypatch.setattr("core.views.client_from_settings", lambda: fake_client(handler))
    client.force_login(user)

    toggle(client, "customer", customer.pk, 0)

    assert json.loads(requests[1].content)["note"] == "- [x] a"
    customer.refresh_from_db()
    assert customer.notes == "- [x] a"
    assert customer.lexware_note == "- [x] a"
    assert customer.lexware_version == 5


def test_a_tick_lexware_refuses_is_not_saved(client, user, monkeypatch, settings):
    settings.LEXWARE_API_KEY = "test-key"
    customer = Customer.objects.create(
        name="ACME GmbH", lexware_id=uuid.uuid4(), lexware_version=1, notes="- [ ] a", lexware_note="- [ ] a"
    )
    monkeypatch.setattr(
        "core.views.client_from_settings",
        lambda: fake_client(lambda request: httpx.Response(409, json={"message": "Version veraltet"})),
    )
    client.force_login(user)

    response = toggle(client, "customer", customer.pk, 0)

    assert "konnte nicht in Lexware gespeichert werden" in response.text
    assert " checked" not in response.text
    customer.refresh_from_db()
    assert customer.notes == "- [ ] a"


def test_preview_renders_the_text_like_the_pages(client, user):
    client.force_login(user)

    response = client.post(
        reverse("core:markdown_preview"), {"text": "## Titel\n\n- [x] fertig\n\nhttps://example.com"}
    )

    assert "<h2>Titel</h2>" in response.text
    assert "disabled" in response.text  # not saved anywhere, so nothing to tick
    assert 'href="https://example.com"' in response.text
    assert "hx-post" not in response.text


def test_preview_of_nothing_says_so(client, user):
    client.force_login(user)

    response = client.post(reverse("core:markdown_preview"), {"text": "  \n"})

    assert "Nichts zur Vorschau" in response.text


def test_markdown_fields_come_with_the_editor(client, user, task):
    client.force_login(user)

    response = client.get(reverse("customers:edit", args=[task.project.customer.pk]))

    assert "data-md-editor" in response.text
    assert response.text.count("data-md-input") == 1
    assert 'data-md-tool="task"' in response.text
    assert 'name="notes"' in response.text
