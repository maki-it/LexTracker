"""A Model Context Protocol server over Streamable HTTP, so AI agents can track time.

Stateless: every request is a JSON-RPC message (or a batch) answered with plain JSON, no event stream.
"""

import json
import logging

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from accounts.models import ApiToken
from mcpserver.tools import TOOLS, ToolError

logger = logging.getLogger(__name__)

# Newest first. A client asking for another version gets the newest one.
PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
SERVER_INFO = {"name": "lextracker", "title": "LexTracker", "version": "1.0"}
INSTRUCTIONS = (
    "LexTracker tracks working time on tasks of customer projects. "
    "Before starting work, find the task with find_tasks or list_projects (create one with create_task "
    "if none fits) and call start_timer. Call stop_timer when the work is done. "
    "Use add_time_entry to book time afterwards."
)

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602


async def _authenticate(request: HttpRequest):
    scheme, _, key = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not key.startswith(ApiToken.PREFIX):
        return None
    token = await ApiToken.objects.select_related("user").filter(key_hash=ApiToken.hash(key.strip())).afirst()
    if token is None or not token.user.is_active or token.user.is_customer:
        return None
    await ApiToken.objects.filter(pk=token.pk).aupdate(last_used_at=timezone.now())
    return token.user


def _error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _result(msg_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _call_tool(user, params: dict) -> dict:
    tool = TOOLS[params["name"]]
    arguments = params.get("arguments") or {}
    unknown = set(arguments) - set(tool.properties)
    missing = [name for name in tool.required if arguments.get(name) is None]
    try:
        if unknown or missing:
            raise ToolError(f"Unbekannte Argumente: {sorted(unknown)}. Fehlende: {missing}.")
        result = tool.handler(user, **arguments)
    except ToolError as exc:
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    text = json.dumps(result, ensure_ascii=False, indent=1)
    return {"content": [{"type": "text", "text": text}], "isError": False}


async def _handle(user, message) -> dict | None:
    """Answer one JSON-RPC message. Notifications get no answer."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
        return _error(message.get("id") if isinstance(message, dict) else None, INVALID_REQUEST, "Invalid request")
    method, params = message["method"], message.get("params") or {}
    if "id" not in message:
        return None
    msg_id = message["id"]

    match method:
        case "initialize":
            asked = params.get("protocolVersion")
            return _result(
                msg_id,
                {
                    "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                    "capabilities": {"tools": {}},
                    "serverInfo": SERVER_INFO,
                    "instructions": INSTRUCTIONS,
                },
            )
        case "ping":
            return _result(msg_id, {})
        case "tools/list":
            return _result(msg_id, {"tools": [t.spec for t in TOOLS.values()]})
        case "tools/call":
            if not isinstance(params, dict) or params.get("name") not in TOOLS:
                return _error(msg_id, INVALID_PARAMS, f"Unknown tool: {params.get('name')}")
            if not isinstance(params.get("arguments") or {}, dict):
                return _error(msg_id, INVALID_PARAMS, "arguments must be an object")
            try:
                return _result(msg_id, await sync_to_async(_call_tool)(user, params))
            except Exception:
                logger.exception("MCP tool %s failed", params["name"])
                return _result(
                    msg_id, {"content": [{"type": "text", "text": "Interner Fehler im Tool."}], "isError": True}
                )
        case _:
            return _error(msg_id, METHOD_NOT_FOUND, f"Method not found: {method}")


@csrf_exempt
async def endpoint(request: HttpRequest) -> HttpResponse:
    user = await _authenticate(request)
    if user is None:
        response = JsonResponse({"error": "API-Token fehlt oder ist ungültig."}, status=401)
        response["WWW-Authenticate"] = 'Bearer realm="lextracker"'
        return response
    if request.method != "POST":
        # No server-initiated messages, so no event stream to open.
        response = HttpResponse(status=405)
        response["Allow"] = "POST"
        return response

    try:
        payload = json.loads(request.body)
    except ValueError:
        return JsonResponse(_error(None, PARSE_ERROR, "Parse error"), status=400)

    if isinstance(payload, list):
        answers = [a for a in [await _handle(user, m) for m in payload] if a is not None]
    else:
        answers = await _handle(user, payload)
    if not answers:
        return HttpResponse(status=202)
    return JsonResponse(answers, safe=False)
