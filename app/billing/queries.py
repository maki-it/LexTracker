from django.db.models import QuerySet
from django.db.models.functions import Coalesce, TruncDate

from billing.models import Invoice

# What "Überfällig" means, for the filter on the invoice list and the number in the sidebar.
OVERDUE_STATUSES = [Invoice.Status.OVERDUE]


async def overdue_count() -> int:
    """How many invoices are overdue, for the sidebar."""
    return await Invoice.objects.filter(status__in=OVERDUE_STATUSES).acount()


def newest_first(invoices: QuerySet[Invoice]) -> QuerySet[Invoice]:
    """Invoices by date, newest first, and within a day by number.

    The date is the invoice date, or the creation date until Lexware has one (drafts). It is added as ``date``.
    """
    return invoices.annotate(date=Coalesce("voucher_date", TruncDate("created_at"))).order_by(
        "-date", "-voucher_number", "-pk"
    )
