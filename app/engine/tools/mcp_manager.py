"""
MCPManager — standardized client for connecting to external MCP servers.

Supports two transport modes:
  - sse (preferred):  connects to a client-local or remote MCP bridge via HTTP/SSE.
                      Used for sovereign deployments where the client runs a local
                      Docker stack and our dashboard reaches it at localhost:<port>.
  - stdio (fallback): spawns a local process and communicates over stdin/stdout.
                      Used in dev/cloud environments without a sovereign stack.

Transport priority: SSE is always attempted first if a URL is configured.
stdio is used only when no URL is available.

Usage:
    manager = MCPManager()
    # Sovereign / SSE (preferred)
    manager.register("gmail", transport="sse", url="http://localhost:8765/mcp",
                     sovereign=True)
    # stdio fallback
    manager.register("gmail", transport="stdio",
                     command=["npx", "-y", "@modelcontextprotocol/server-gmail"])
    result = manager.call_tool("gmail", "send_email", {"to": "...", "subject": "...", "body": "..."})
"""

from __future__ import annotations

import json
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import httpx


# ---------------------------------------------------------------------------
# Layman-friendly tool name translations
# ---------------------------------------------------------------------------

_LAYMAN_NAMES: dict[str, str] = {
    # Gmail
    "send_mime_message":        "Send Official Email",
    "send_email":               "Send Official Email",
    "list_messages":            "View Inbox Messages",
    "get_message":              "Read an Email",
    "search_messages":          "Search Emails",
    "create_draft":             "Draft an Email",
    "reply_to_message":         "Reply to an Email",
    "delete_message":           "Delete an Email",
    # Google Sheets
    "append_values":            "Add Rows to Spreadsheet",
    "update_values":            "Update Spreadsheet Data",
    "get_values":               "Read Spreadsheet Data",
    "create_spreadsheet":       "Create a New Spreadsheet",
    "batch_update":             "Bulk Update Spreadsheet",
    "clear_values":             "Clear Spreadsheet Range",
    # Slack
    "post_message":             "Send a Slack Message",
    "send_message":             "Send a Slack Message",
    "list_channels":            "List Slack Channels",
    "get_channel_history":      "Read Channel Messages",
    "upload_file":              "Share a File on Slack",
    "create_channel":           "Create a Slack Channel",
    "add_reaction":             "React to a Message",
}


def layman_name(raw_name: str) -> str:
    """Return a human-friendly display name for an MCP tool."""
    return _LAYMAN_NAMES.get(raw_name, raw_name.replace("_", " ").title())


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class MCPTool:
    server_id: str
    name: str                          # raw MCP tool name
    display_name: str                  # layman-friendly name
    description: str
    input_schema: dict = field(default_factory=dict)


@dataclass
class MCPServer:
    server_id: str
    transport: str                     # "stdio" | "sse"
    # stdio fields
    command: Optional[list[str]] = None
    env: Optional[dict[str, str]] = None
    # sse / sovereign fields
    url: Optional[str] = None
    headers: Optional[dict[str, str]] = None
    sovereign: bool = False            # True = client-local sovereign deployment
    # runtime state
    tools: list[MCPTool] = field(default_factory=list)
    verified: bool = False             # True after successful health ping
    _process: Optional[subprocess.Popen] = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _seq: int = field(default=0, repr=False)


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

def _jsonrpc(method: str, params: dict, seq: int) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": seq, "method": method, "params": params})


def _parse_response(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": {"message": f"Invalid JSON: {raw[:200]}"}}


# ---------------------------------------------------------------------------
# MCPManager
# ---------------------------------------------------------------------------

class MCPManager:
    """
    Central registry and executor for MCP server connections.
    Thread-safe; safe to use as a module-level singleton.
    """

    def __init__(self) -> None:
        self._servers: dict[str, MCPServer] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        server_id: str,
        *,
        transport: str = "stdio",
        command: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
        url: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
        sovereign: bool = False,
    ) -> None:
        """
        Register an MCP server. Does not connect until first use.

        If both url and command are provided, SSE (url) is tried first.
        Set sovereign=True for client-local Docker deployments.
        """
        if transport not in ("stdio", "sse"):
            raise ValueError(f"transport must be 'stdio' or 'sse', got '{transport}'")
        # Upgrade transport to sse when a URL is present, regardless of what caller passed
        effective_transport = "sse" if url else transport
        self._servers[server_id] = MCPServer(
            server_id=server_id,
            transport=effective_transport,
            command=command,
            env=env,
            url=url,
            headers=headers,
            sovereign=sovereign,
        )

    def is_registered(self, server_id: str) -> bool:
        return server_id in self._servers

    # ------------------------------------------------------------------
    # Tool discovery
    # ------------------------------------------------------------------

    def list_tools(self, server_id: str) -> list[MCPTool]:
        """Connect (if needed) and return the server's tool list."""
        server = self._get_server(server_id)
        if not server.tools:
            server.tools = self._discover_tools(server)
        return server.tools

    def get_tool_meta(self, server_id: str, tool_name: str) -> Optional[MCPTool]:
        for t in self.list_tools(server_id):
            if t.name == tool_name:
                return t
        return None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def call_tool(self, server_id: str, tool_name: str, arguments: dict) -> Any:
        """
        Execute a tool on the specified MCP server.
        SSE is always tried first if a URL is configured; stdio is the fallback.
        Returns the result content (dict or str).
        """
        server = self._get_server(server_id)
        # SSE priority: use SSE whenever a URL is present
        if server.url:
            return self._call_sse(server, tool_name, arguments)
        return self._call_stdio(server, tool_name, arguments)

    def get_tool(self, server_id: str, tool_name: str) -> Callable[[dict], Any]:
        """Return a callable that invokes the named tool on the server."""
        def _invoke(arguments: dict) -> Any:
            return self.call_tool(server_id, tool_name, arguments)
        _invoke.__name__ = f"{server_id}.{tool_name}"
        return _invoke

    # ------------------------------------------------------------------
    # Connector metadata (for /ai/build response)
    # ------------------------------------------------------------------

    def connector_payload(self, server_id: str) -> dict:
        """Return a frontend-ready connector descriptor."""
        server = self._servers.get(server_id)
        if not server:
            return {}
        tools = []
        try:
            tools = [
                {"name": t.name, "display_name": t.display_name, "description": t.description}
                for t in self.list_tools(server_id)
            ]
        except Exception:
            pass
        return {
            "id": server_id,
            "transport": server.transport,
            "sovereign": server.sovereign,
            "verified": server.verified,
            "connected": server._process is not None or bool(server.url),
            "tools": tools,
        }

    # ------------------------------------------------------------------
    # Sovereign verification
    # ------------------------------------------------------------------

    def ping_sovereign(self, server_id: str) -> dict:
        """
        Ping the local SSE bridge's /health endpoint to confirm the client's
        sovereign stack is running.  Returns a status dict the API layer can
        forward directly to the frontend (drives the Privacy Shield icon).
        """
        server = self._servers.get(server_id)
        if not server:
            return {"ok": False, "reason": f"Server '{server_id}' not registered."}
        if not server.url:
            return {"ok": False, "reason": "No SSE URL configured — sovereign mode requires a URL."}

        health_url = server.url.rstrip("/") + "/health"
        try:
            resp = httpx.get(health_url, headers=server.headers or {}, timeout=5)
            if resp.status_code == 200:
                server.verified = True
                return {
                    "ok": True,
                    "server_id": server_id,
                    "sovereign": server.sovereign,
                    "url": server.url,
                    "shield": "active",
                    "message": "Privacy Shield active — your data is processing locally.",
                }
            return {
                "ok": False,
                "server_id": server_id,
                "status_code": resp.status_code,
                "reason": f"Local server returned HTTP {resp.status_code}.",
            }
        except httpx.ConnectError:
            return {
                "ok": False,
                "server_id": server_id,
                "reason": (
                    "Could not reach the local server. "
                    "Make sure you ran: docker compose -f agentic-mind-local.yml up -d"
                ),
            }
        except Exception as exc:
            return {"ok": False, "server_id": server_id, "reason": str(exc)}

    def ping_url(self, url: str) -> dict:
        """
        Ad-hoc ping of any SSE bridge URL (used before the server is registered).
        Called by the /sovereign/verify endpoint with the URL from the installer.
        """
        health_url = url.rstrip("/") + "/health"
        try:
            resp = httpx.get(health_url, timeout=5)
            if resp.status_code == 200:
                return {
                    "ok": True,
                    "url": url,
                    "shield": "active",
                    "message": "Privacy Shield active — your data is processing locally.",
                }
            return {"ok": False, "url": url, "reason": f"HTTP {resp.status_code}"}
        except httpx.ConnectError:
            return {
                "ok": False,
                "url": url,
                "reason": (
                    "Local server not reachable. "
                    "Run: docker compose -f agentic-mind-local.yml up -d"
                ),
            }
        except Exception as exc:
            return {"ok": False, "url": url, "reason": str(exc)}

    # ------------------------------------------------------------------
    # Internal — server lookup
    # ------------------------------------------------------------------

    def _get_server(self, server_id: str) -> MCPServer:
        server = self._servers.get(server_id)
        if not server:
            raise KeyError(f"MCP server '{server_id}' is not registered.")
        return server

    # ------------------------------------------------------------------
    # Internal — stdio transport
    # ------------------------------------------------------------------

    def _ensure_stdio_process(self, server: MCPServer) -> None:
        with server._lock:
            if server._process and server._process.poll() is None:
                return
            if not server.command:
                raise ValueError(f"stdio server '{server.server_id}' has no command configured.")
            import os
            env = {**os.environ, **(server.env or {})}
            server._process = subprocess.Popen(
                server.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            # MCP initialization handshake
            self._stdio_request(server, "initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "agentic-mind", "version": "1.0.0"},
            })
            self._stdio_request(server, "notifications/initialized", {})

    def _stdio_request(self, server: MCPServer, method: str, params: dict) -> dict:
        with server._lock:
            server._seq += 1
            msg = _jsonrpc(method, params, server._seq) + "\n"
            server._process.stdin.write(msg)
            server._process.stdin.flush()
            raw = server._process.stdout.readline()
            return _parse_response(raw)

    def _call_stdio(self, server: MCPServer, tool_name: str, arguments: dict) -> Any:
        self._ensure_stdio_process(server)
        resp = self._stdio_request(server, "tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        if "error" in resp:
            raise RuntimeError(f"MCP error from '{server.server_id}': {resp['error']}")
        return resp.get("result", {})

    def _discover_tools_stdio(self, server: MCPServer) -> list[MCPTool]:
        self._ensure_stdio_process(server)
        resp = self._stdio_request(server, "tools/list", {})
        raw_tools = resp.get("result", {}).get("tools", [])
        return [
            MCPTool(
                server_id=server.server_id,
                name=t["name"],
                display_name=layman_name(t["name"]),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
            )
            for t in raw_tools
        ]

    # ------------------------------------------------------------------
    # Internal — SSE transport
    # ------------------------------------------------------------------

    def _call_sse(self, server: MCPServer, tool_name: str, arguments: dict) -> Any:
        if not server.url:
            raise ValueError(f"SSE server '{server.server_id}' has no URL configured.")
        payload = {"tool": tool_name, "arguments": arguments}
        resp = httpx.post(
            server.url.rstrip("/") + "/tools/call",
            json=payload,
            headers=server.headers or {},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _discover_tools_sse(self, server: MCPServer) -> list[MCPTool]:
        if not server.url:
            return []
        try:
            resp = httpx.get(
                server.url.rstrip("/") + "/tools/list",
                headers=server.headers or {},
                timeout=10,
            )
            resp.raise_for_status()
            raw_tools = resp.json().get("tools", [])
            return [
                MCPTool(
                    server_id=server.server_id,
                    name=t["name"],
                    display_name=layman_name(t["name"]),
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                )
                for t in raw_tools
            ]
        except Exception:
            return []

    def _discover_tools(self, server: MCPServer) -> list[MCPTool]:
        # SSE priority: if a URL is present, always use SSE regardless of declared transport
        if server.url:
            return self._discover_tools_sse(server)
        return self._discover_tools_stdio(server)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def shutdown(self, server_id: Optional[str] = None) -> None:
        """Terminate stdio processes. Pass None to shut down all."""
        targets = [server_id] if server_id else list(self._servers)
        for sid in targets:
            s = self._servers.get(sid)
            if s and s._process:
                try:
                    s._process.stdin.close()
                    s._process.terminate()
                except Exception:
                    pass
                s._process = None


# ---------------------------------------------------------------------------
# Well-known server presets
# ---------------------------------------------------------------------------

WELL_KNOWN_SERVERS: dict[str, dict] = {
    "gmail": {
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-gmail"],
        "display_label": "Gmail",
        "button_label": "Connect Gmail",
        "icon": "mail",
        "description": "Send emails, read inbox, and manage drafts directly from the co-worker.",
    },
    "google_sheets": {
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-google-sheets"],
        "display_label": "Google Sheets",
        "button_label": "Connect Spreadsheet",
        "icon": "table",
        "description": "Read, append, and update spreadsheet data for tracking and reporting.",
    },
    "slack": {
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-slack"],
        "display_label": "Slack",
        "button_label": "Connect Slack",
        "icon": "message-circle",
        "description": "Post messages and notifications to Slack channels.",
    },
}


def connector_button(server_id: str) -> dict:
    """Return the frontend button descriptor for a well-known server."""
    meta = WELL_KNOWN_SERVERS.get(server_id, {})
    return {
        "server_id": server_id,
        "display_label": meta.get("display_label", server_id.replace("_", " ").title()),
        "button_label": meta.get("button_label", f"Connect {server_id}"),
        "icon": meta.get("icon", "plug"),
        "description": meta.get("description", ""),
    }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_manager: Optional[MCPManager] = None


def get_mcp_manager() -> MCPManager:
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager
