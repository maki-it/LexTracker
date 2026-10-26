from billing.models import Invoice

# What "Überfällig" means, for the filter on the invoice list and the number in the sidebar.
OVERDUE_STATUSES = [Invoice.Status.OVERDUE]


async def overdue_count() -> int:
    """How many invoices are overdue, for the sidebar."""
    return await Invoice.objects.filter(status__in=OVERDUE_STATUSES).acount()
