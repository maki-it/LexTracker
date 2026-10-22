"""User management for administrators: employees and customer logins, invited by a link."""

from asgiref.sync import sync_to_async
from django.contrib import messages
from django.contrib.auth.tokens import default_token_generator
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.http import require_GET, require_http_methods

from accounts.forms import UserForm
from accounts.models import User
from core.dialogs import navigate
from core.shortcuts import arender


def invite_url(request: HttpRequest, user: User) -> str:
    """A link to set a password. It stops working once a password is set, or after a week."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return request.build_absolute_uri(reverse("accounts:invite", args=[uid, token]))


async def _get_user(pk: int) -> User:
    try:
        return await User.objects.select_related("customer").aget(pk=pk)
    except User.DoesNotExist as exc:
        raise Http404 from exc


@require_GET
async def user_list(request: HttpRequest) -> HttpResponse:
    users = [u async for u in User.objects.select_related("customer").order_by("role", "username")]
    return render(request, "accounts/users/list.html", {"users": users})


@require_http_methods(["GET", "POST"])
async def user_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    user = await _get_user(pk) if pk else User(role=User.Role.EMPLOYEE)
    form = UserForm(request.POST or None, instance=user, acting_user=request.user)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        if user.pk is None:
            user.set_unusable_password()
            await sync_to_async(form.save)()
            return navigate("users:invite", pk=user.pk)
        await sync_to_async(form.save)()
        messages.success(request, f"{user.get_username()} gespeichert.")
        return redirect("users:list")
    return await arender(request, "accounts/users/form.html", {"form": form, "edited": user})


@require_GET
async def invite_link(request: HttpRequest, pk: int) -> HttpResponse:
    user = await _get_user(pk)
    if not user.is_active:
        messages.error(request, "Der Benutzer ist deaktiviert. Aktiviere ihn zuerst.")
        return redirect("users:list")
    return render(request, "accounts/users/invite.html", {"edited": user, "url": invite_url(request, user)})
