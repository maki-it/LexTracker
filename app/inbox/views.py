"""The messages of the signed-in user: the panel behind the bell, the page with all of them and the actions."""

from uuid import UUID

from django.db.models import Count, Q
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

# How many messages the panel behind the bell lists. The page "alle" has the rest.
PANEL_SIZE = 8

# The filters on the page with all messages: the key in the URL, its label and what it selects.
FILTERS = {
    "ungelesen": ("Ungelesen", Q(read_at__isnull=True)),
    "kritisch": (Level.CRITICAL.label, Q(level=Level.CRITICAL)),
    "warnung": (Level.WARNING.label, Q(level=Level.WARNING)),
    "info": (Level.INFO.label, Q(level=Level.INFO)),
    "debug": (Level.DEBUG.label, Q(level=Level.DEBUG)),
}


async def _get_message(request: HttpRequest, pk: UUID) -> Message:
    """Only the user's own messages: anyone else's is "not found"."""
    try:
        return await Message.objects.aget(pk=pk, user=request.user)
    except Message.DoesNotExist as exc:
        raise Http404 from exc


@require_GET
async def bell(request: HttpRequest) -> HttpResponse:
    """The bell alone, which the sidebar reloads every minute and after something changed."""
    return render(request, "inbox/_bell.html", {"inbox": await service.summary(request.user)})


async def _panel(request: HttpRequest) -> HttpResponse:
    messages = [m async for m in service.visible_to(request.user)[: PANEL_SIZE + 1]]
    context = {
        "messages_list": messages[:PANEL_SIZE],
        "more": len(messages) > PANEL_SIZE,
        "unread": await service.visible_to(request.user).filter(read_at__isnull=True).acount(),
    }
    return render(request, "inbox/panel.html", context)


@require_GET
async def panel(request: HttpRequest) -> HttpResponse:
    """The latest messages, in the dialog. Without JavaScript it is a page of its own."""
    return await _panel(request)


@require_GET
async def all_messages(request: HttpRequest) -> HttpResponse:
    visible = service.visible_to(request.user)
    key = request.GET.get("filter", "")
    messages = visible.filter(FILTERS[key][1]) if key in FILTERS else visible
    page = await apage(request, messages)
    # Where the forms on the page return to: this page with its filter, but not scrolled to a later batch.
    next_url = f"{reverse('inbox:all')}?filter={key}" if key in FILTERS else reverse("inbox:all")
    if wants_rows(request):
        return render(request, "inbox/_rows.html", {"page": page, "next_url": next_url})
    counts = await visible.aaggregate(total=Count("pk"), **{k: Count("pk", filter=q) for k, (_, q) in FILTERS.items()})
    # Debug is hidden by default; its filter would only ever be empty then.
    filters = [
        (k, label, counts[k])
        for k, (label, _) in FILTERS.items()
        if k != "debug" or request.user.message_level <= Level.DEBUG
    ]
    context = {
        "page": page,
        "filters": filters,
        "active": key if key in FILTERS else "",
        "total": counts["total"],
        "next_url": next_url,
    }
    return render(request, "inbox/all.html", context)


def _back(request: HttpRequest) -> str:
    """Where a form on the page with all messages returns to: that page, with its filter."""
    target = request.POST.get("next", "")
    allowed = url_has_allowed_host_and_scheme(target, allowed_hosts=None) and target.startswith(reverse("inbox:all"))
    return target if allowed else reverse("inbox:all")


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
