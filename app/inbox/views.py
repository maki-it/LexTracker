"""The messages of the signed-in user: the panel behind the bell, the page with all of them and the actions."""

from uuid import UUID

from django.db.models import Count, Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from core.dialogs import in_dialog, navigate
from core.paging import apage, wants_rows
from inbox import service
from inbox.levels import Level
from inbox.models import Message
from reminders import queries as reminder_queries

# How many messages the panel behind the bell lists. The page "all" has the rest.
PANEL_SIZE = 8

# The filters of the panel and of the page with all messages: the key in the URL, its label and what it selects.
FILTERS = {
    "unread": ("Ungelesen", Q(read_at__isnull=True)),
    "critical": (Level.CRITICAL.label, Q(level=Level.CRITICAL)),
    "warning": (Level.WARNING.label, Q(level=Level.WARNING)),
    "info": (Level.INFO.label, Q(level=Level.INFO)),
    "debug": (Level.DEBUG.label, Q(level=Level.DEBUG)),
}
# Both start with the unread messages. This key in the URL selects everything instead.
DEFAULT_FILTER = "unread"
SHOW_ALL = "all"


def _filter_key(request: HttpRequest) -> str:
    """The filter of the request: from the URL, or from the form of an action in the panel."""
    key = request.GET.get("filter") or request.POST.get("filter") or DEFAULT_FILTER
    return key if key in FILTERS or key == SHOW_ALL else DEFAULT_FILTER


def _filtered(messages: QuerySet[Message], key: str) -> QuerySet[Message]:
    return messages if key == SHOW_ALL else messages.filter(FILTERS[key][1])


def _all_url(key: str) -> str:
    return f"{reverse('inbox:all')}?filter={key}"


async def _get_message(request: HttpRequest, pk: UUID) -> Message:
    """Only the user's own messages: anyone else's is "not found"."""
    try:
        return await Message.objects.aget(pk=pk, user=request.user)
    except Message.DoesNotExist as exc:
        raise Http404 from exc


@require_GET
async def bell(request: HttpRequest) -> HttpResponse:
    """The bell alone, which the sidebar reloads every minute and after something changed."""
    context = {"inbox": await service.summary(request.user)}
    if request.user.is_admin:
        # The sidebar link to the reminders shows how many are due; the bell brings the new number along.
        context |= {"oob": True, "reminders_due": await reminder_queries.due_count(request.user)}
    return render(request, "inbox/_bell.html", context)


async def _panel(request: HttpRequest) -> HttpResponse:
    key = _filter_key(request)
    messages = [m async for m in _filtered(service.visible_to(request.user), key)[: PANEL_SIZE + 1]]
    context = {
        "messages_list": messages[:PANEL_SIZE],
        "more": len(messages) > PANEL_SIZE,
        "unread": await service.visible_to(request.user).filter(read_at__isnull=True).acount(),
        "filter_key": key,
        "show_all": key == SHOW_ALL,
        "all_url": _all_url(key),
    }
    return render(request, "inbox/panel.html", context)


@require_GET
async def panel(request: HttpRequest) -> HttpResponse:
    """The latest messages, in the dialog. Without JavaScript it is a page of its own."""
    return await _panel(request)


@require_GET
async def all_messages(request: HttpRequest) -> HttpResponse:
    visible = service.visible_to(request.user)
    key = _filter_key(request)
    page = await apage(request, _filtered(visible, key))
    # Where the forms on the page return to: this page with its filter, but not scrolled to a later batch.
    next_url = _all_url(key)
    if wants_rows(request):
        return render(request, "inbox/_rows.html", {"page": page, "next_url": next_url})
    counts = await visible.aaggregate(total=Count("pk"), **{k: Count("pk", filter=q) for k, (_, q) in FILTERS.items()})
    filters = []
    for k, (label, _) in FILTERS.items():
        # Debug is hidden by default; its filter would only ever be empty then.
        if k == "debug" and request.user.message_level > Level.DEBUG:
            continue
        filters.append((k, label, counts[k]))
        if k == DEFAULT_FILTER:
            filters.append((SHOW_ALL, "Alle", counts["total"]))
    context = {"page": page, "filters": filters, "active": key, "next_url": next_url}
    return render(request, "inbox/all.html", context)


def _back(request: HttpRequest) -> str:
    """Where a form on the page with all messages returns to: that page, with its filter."""
    target = request.POST.get("next", "")
    allowed = url_has_allowed_host_and_scheme(target, allowed_hosts=None) and target.startswith(reverse("inbox:all"))
    return target if allowed else _all_url(_filter_key(request))


async def _changed(request: HttpRequest) -> HttpResponse:
    """After an action: in the dialog the panel again, with the bell told to reload; elsewhere the page again."""
    if not in_dialog(request):
        return redirect(_back(request))
    response = await _panel(request)
    response["HX-Trigger"] = "inbox-changed"
    return response


@require_POST
async def read(request: HttpRequest, pk: UUID) -> HttpResponse:
    message = await _get_message(request, pk)
    if message.is_unread:
        await Message.objects.filter(pk=pk).aupdate(read_at=timezone.now())
    return await _changed(request)


@require_POST
async def read_all(request: HttpRequest) -> HttpResponse:
    await service.visible_to(request.user).filter(read_at__isnull=True).aupdate(read_at=timezone.now())
    return await _changed(request)


@require_POST
async def delete(request: HttpRequest, pk: UUID) -> HttpResponse:
    message = await _get_message(request, pk)
    await message.adelete()
    return await _changed(request)


@require_GET
async def open_message(request: HttpRequest, pk: UUID) -> HttpResponse:
    """Mark the message as read and go to what it is about."""
    message = await _get_message(request, pk)
    if message.is_unread:
        await Message.objects.filter(pk=pk).aupdate(read_at=timezone.now())
    # From the dialog, go to the page itself instead of reloading the one behind the dialog.
    return navigate(message.url or "inbox:all")
