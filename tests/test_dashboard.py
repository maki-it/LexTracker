import pytest
from django.urls import reverse

from tracking.models import TimeEntry


@pytest.mark.django_db(transaction=True)
async def test_dashboard_shows_running_timer(async_client, user, task):
    await TimeEntry.objects.acreate(user=user, task=task)
    await async_client.aforce_login(user)

    response = await async_client.get(reverse("core:dashboard"))

    assert response.status_code == 200
    assert "Entwicklung" in response.text
    assert "ACME GmbH" in response.text
