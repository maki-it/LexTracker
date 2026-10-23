import pytest
from django.urls import reverse

from core.templatetags.markdown import markdown
from customers.models import Customer

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


def test_headings_stay_text():
    assert "<h1" not in markdown("# Titel")


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
