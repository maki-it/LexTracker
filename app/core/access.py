"""Which parts of the app each role may open.

Administrators may open everything. Employees track their own time; customers only see the portal.
Views still scope their data to the user, e.g. time entries to ``request.user``.
"""

from collections.abc import Awaitable, Callable

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import Resolver404, resolve
from django.utils.decorators import async_only_middleware

# By URL namespace. The Django admin checks is_staff itself.
EMPLOYEE_NAMESPACES = {"core", "tracking", "account", "accounts", "mcp", "admin"}
EMPLOYEE_DENIED = {"core:settings"}
CUSTOMER_NAMESPACES = {"portal", "account", "accounts", "admin"}
CUSTOMER_DENIED = {"account:token_create", "account:token_revoke"}


PUBLIC_VIEWS = {"core:health"}


def allowed(user, view_name: str) -> bool:
    if user.is_admin or view_name in PUBLIC_VIEWS:
        return True
    namespace = view_name.split(":", 1)[0]
    if user.is_employee:
        return namespace in EMPLOYEE_NAMESPACES and view_name not in EMPLOYEE_DENIED
    return namespace in CUSTOMER_NAMESPACES and view_name not in CUSTOMER_DENIED


@async_only_middleware
def RoleAccessMiddleware(get_response: Callable[[HttpRequest], Awaitable[HttpResponse]]):
    async def middleware(request: HttpRequest) -> HttpResponse:
        if request.user.is_authenticated and not request.user.is_admin:
            try:
                view_name = resolve(request.path_info).view_name
            except Resolver404:
                return await get_response(request)
            if not allowed(request.user, view_name):
                if request.user.is_customer and view_name == "core:dashboard":
                    return redirect("portal:overview")
                raise PermissionDenied
        return await get_response(request)

    return middleware
