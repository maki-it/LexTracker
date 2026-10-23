"""Ready-to-copy setups of the MCP server for common AI clients, shown on the account page.

Formats as documented by the clients in October 2026:
- Claude Code: https://code.claude.com/docs/en/mcp
- Claude (desktop app and web): https://claude.com/docs/connectors/custom/add-unlisted
- VS Code: https://code.visualstudio.com/docs/copilot/reference/mcp-configuration
- Cursor: https://cursor.com/docs/context/mcp
- Codex: https://developers.openai.com/codex/mcp
"""

import json
from dataclasses import dataclass, field

SERVER_NAME = "lextracker"
TOKEN_PLACEHOLDER = "DEIN_TOKEN"
TOKEN_ENV = "LEXTRACKER_TOKEN"


@dataclass
class Snippet:
    label: str
    text: str


@dataclass
class Client:
    slug: str
    name: str
    intro: str
    snippets: list[Snippet]
    notes: list[str] = field(default_factory=list)


def _json(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def clients(url: str, token: str = "") -> list[Client]:
    """The setups for the MCP address `url`, with `token` filled in (or a placeholder without one)."""
    token = token or TOKEN_PLACEHOLDER
    bearer = f"Bearer {token}"
    return [
        Client(
            "claude-code",
            "Claude Code",
            "Im Terminal ausführen. Mit <code>--scope user</code> steht LexTracker in all deinen Projekten bereit, "
            "Claude Code speichert das in <code>~/.claude.json</code>.",
            [
                Snippet(
                    "Terminal",
                    f"claude mcp add --transport http --scope user {SERVER_NAME} {url} \\\n"
                    f'  --header "Authorization: {bearer}"',
                ),
                Snippet(
                    "Oder fürs ganze Team: .mcp.json im Projektordner",
                    _json(
                        {
                            "mcpServers": {
                                SERVER_NAME: {
                                    "type": "http",
                                    "url": url,
                                    "headers": {"Authorization": f"Bearer ${{{TOKEN_ENV}}}"},
                                }
                            }
                        }
                    ),
                ),
            ],
            [
                f"Die <code>.mcp.json</code> kann ins Git, der Token steht nicht darin. Jeder setzt ihn selbst "
                f"als Umgebungsvariable <code>{TOKEN_ENV}</code>.",
                "Prüfen mit <code>claude mcp list</code> oder in Claude Code mit <code>/mcp</code>.",
            ],
        ),
        Client(
            "claude",
            "Claude Desktop und Web",
            "In Claude unter <strong>Customize → Connectors</strong> auf <strong>Add custom connector</strong> "
            "klicken. Bei <strong>Authentication</strong> <strong>No sign-in</strong> wählen und den Token unter "
            "<strong>Request headers</strong> als Header <code>authorization</code> eintragen.",
            [
                Snippet("MCP server URL", url),
                Snippet("Wert für den Header authorization", bearer),
            ],
            [
                "Claude verbindet sich aus der Anthropic-Cloud. LexTracker muss dafür über HTTPS aus dem Internet "
                "erreichbar sein.",
                "Request headers sind bei Claude noch in der Beta und nicht in jedem Konto sichtbar. Fehlt der "
                "Abschnitt, nutze Claude Code.",
                "Die Datei <code>claude_desktop_config.json</code> ist nur für lokale Server gedacht, "
                "nicht für LexTracker.",
            ],
        ),
        Client(
            "vscode",
            "VS Code",
            "In <code>.vscode/mcp.json</code> im Projekt eintragen. Für alle Projekte öffnest du die Datei über "
            "die Befehlspalette mit <strong>MCP: Open User Configuration</strong>.",
            [
                Snippet(
                    "mcp.json",
                    _json(
                        {
                            "inputs": [
                                {
                                    "type": "promptString",
                                    "id": "lextracker-token",
                                    "description": "LexTracker API-Token",
                                    "password": True,
                                }
                            ],
                            "servers": {
                                SERVER_NAME: {
                                    "type": "http",
                                    "url": url,
                                    "headers": {"Authorization": "Bearer ${input:lextracker-token}"},
                                }
                            },
                        }
                    ),
                )
            ],
            ["VS Code fragt beim ersten Start nach dem Token und speichert ihn sicher, die Datei enthält ihn nicht."],
        ),
        Client(
            "cursor",
            "Cursor",
            "In <code>~/.cursor/mcp.json</code> eintragen, dann steht LexTracker in allen Projekten bereit. "
            "Nur für ein Projekt geht es in <code>.cursor/mcp.json</code> im Projektordner.",
            [
                Snippet(
                    "mcp.json",
                    _json({"mcpServers": {SERVER_NAME: {"url": url, "headers": {"Authorization": bearer}}}}),
                )
            ],
            [
                f"Liegt die Datei im Projekt und kommt ins Git, schreib statt des Tokens "
                f"<code>${{env:{TOKEN_ENV}}}</code> und setze die Umgebungsvariable.",
            ],
        ),
        Client(
            "codex",
            "Codex",
            f"In <code>~/.codex/config.toml</code> eintragen. Codex liest den Token aus der Umgebungsvariable "
            f"<code>{TOKEN_ENV}</code>, z. B. aus deiner <code>~/.zshrc</code> oder <code>~/.bashrc</code>.",
            [
                Snippet(
                    "config.toml",
                    f'[mcp_servers.{SERVER_NAME}]\nurl = "{url}"\nbearer_token_env_var = "{TOKEN_ENV}"',
                ),
                Snippet("Umgebungsvariable", f'export {TOKEN_ENV}="{token}"'),
            ],
        ),
    ]
