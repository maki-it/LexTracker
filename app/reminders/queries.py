from django.db.models import QuerySet
from django.utils import timezone

from reminders.models import Reminder

# How many done reminders a customer's or project's page still lists.
RECENT_DONE = 5


def with_context(reminders: QuerySet[Reminder]) -> QuerySet[Reminder]:
    return reminders.select_related("customer", "project__customer")


async def for_page(reminders: QuerySet[Reminder]) -> list[Reminder]:
    """The open reminders by due date (those without a date last), then the most recent done ones."""
    reminders = with_context(reminders)
    open_ = [r async for r in reminders.filter(done_at__isnull=True)]
    done = [r async for r in reminders.filter(done_at__isnull=False).order_by("-done_at")[:RECENT_DONE]]
    return open_ + done


async def due_count(user) -> int:
    """How many of the user's open reminders are due, for the sidebar."""
    return await Reminder.objects.filter(user=user, done_at__isnull=True, due_at__lte=timezone.now()).acount()
