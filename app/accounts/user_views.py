"""User management for administrators: employees and customer logins, invited by a link or by e-mail."""

from uuid import UUID

from asgiref.sync import sync_to_async
from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts import links
from accounts.forms import UserForm
from accounts.models import User
from core.dialogs import navigate
from core.models import AppSettings
from core.shortcuts import arender
from tracking.models import TimeEntry


async def _get_user(pk: UUID) -> User:
    try:
        return await User.objects.select_related("customer").aget(pk=pk)
    except User.DoesNotExist as exc:
        raise Http404 from exc


@require_GET
async def user_list(request: HttpRequest) -> HttpResponse:
    users = [
        u
        async for u in User.objects.select_related("customer")
        .prefetch_related("bookable_customers", "bookable_projects")
        .order_by("role", "username")
    ]
    return render(request, "accounts/users/list.html", {"users": users})


@require_http_methods(["GET", "POST"])
async def user_form(request: HttpRequest, pk: UUID | None = None) -> HttpResponse:
    user = await _get_user(pk) if pk else User(role=User.Role.EMPLOYEE)
    # Built in a thread: the initial values of the many-to-many fields come from the database.
    form = await sync_to_async(UserForm)(request.POST or None, instance=user, acting_user=request.user)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        if user._state.adding:
            user.set_unusable_password()
            await sync_to_async(form.save)()
            if (await AppSettings.aload()).invite_by_mail and await links.can_send_invitation(user):
                await links.send_invitation(request, user)
                messages.success(request, _("Einladung an %(email)s ist unterwegs.") % {"email": user.email})
            return navigate("users:invite", pk=user.pk)
        await sync_to_async(form.save)()
        messages.success(request, _("%(name)s gespeichert.") % {"name": user.get_username()})
        return redirect("users:list")
    is_new = user._state.adding
    has_entries = not is_new and await TimeEntry.objects.filter(user=user).aexists()
    return await arender(
        request,
        "accounts/users/form.html",
        {"form": form, "edited": user, "is_new": is_new, "has_entries": has_entries},
    )


@require_POST
async def user_delete(request: HttpRequest, pk: UUID) -> HttpResponse:
    user = await _get_user(pk)
    if user.pk == request.user.pk:
        messages.error(request, _("Du kannst dich nicht selbst löschen."))
        return redirect("users:list")
    # Booked time must not disappear with its user; such users can be deactivated instead.
    if await TimeEntry.objects.filter(user=user).aexists():
        messages.error(
            request,
            _("%(name)s hat gebuchte Zeiten und kann nicht gelöscht werden. Deaktiviere den Zugang.")
            % {"name": user.get_username()},
        )
        return redirect("users:list")
    await user.adelete()
    messages.success(request, _("%(name)s gelöscht.") % {"name": user.get_username()})
    return redirect("users:list")


@require_http_methods(["GET", "POST"])
async def invite_link(request: HttpRequest, pk: UUID) -> HttpResponse:
    user = await _get_user(pk)
    if not user.is_active:
        messages.error(request, _("Der Benutzer ist deaktiviert. Aktiviere ihn zuerst."))
        return redirect("users:list")
    can_send = await links.can_send_invitation(user)
    if request.method == "POST" and can_send:
        await links.send_invitation(request, user)
        messages.success(request, _("Einladung an %(email)s ist unterwegs.") % {"email": user.email})
        return redirect("users:invite", pk=user.pk)
    context = {"edited": user, "url": await links.invite_url(request, user), "can_send": can_send}
    return render(request, "accounts/users/invite.html", context)
