import pytest

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
