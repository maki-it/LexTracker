import shutil
import subprocess

import pytest
from django.conf import settings

from accounts.models import User
from customers.models import Customer
from projects.models import Project, Task


@pytest.fixture
def user(db) -> User:
    return User.objects.create_user(username="kim", password="geheim-123")


@pytest.fixture
def task(db) -> Task:
    customer = Customer.objects.create(name="ACME GmbH")
    project = Project.objects.create(customer=customer, name="Website")
    return Task.objects.create(project=project, name="Entwicklung")


@pytest.fixture(scope="session")
def english_catalog() -> bool:
    """Compile the English translation if that is needed and possible (``make messages`` does this for development).

    False if there is no compiled catalog, so the tests of the English interface can skip.
    """
    po = settings.LOCALE_PATHS[0] / "en" / "LC_MESSAGES" / "django.po"
    mo = po.with_suffix(".mo")
    if shutil.which("msgfmt") and (not mo.exists() or mo.stat().st_mtime < po.stat().st_mtime):
        subprocess.run(["msgfmt", "--check-format", "-o", str(mo), str(po)], check=True)
    return mo.exists()


@pytest.fixture
def english(english_catalog):
    if not english_catalog:
        pytest.skip("The English translation is not compiled (needs gettext).")
