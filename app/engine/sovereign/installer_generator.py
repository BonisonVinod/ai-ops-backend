"""
InstallerGenerator — produces client-side sovereign deployment artefacts.

Two outputs per request:
  1. config.json   — tells the local MCP bridge which servers to expose and
                     what SSE port/path to listen on so our dashboard can reach it.
  2. docker-compose.yml — one-command container stack the client runs locally;
                          no data leaves their machine.

Design principle: every generated file is self-contained.  The client only needs
Docker (or Node ≥18) installed — nothing else.
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass, field
from typing import Optional

from app.engine.tools.mcp_manager import WELL_KNOWN_SERVERS


# ---------------------------------------------------------------------------
# Public data model
# ---------------------------------------------------------------------------

@dataclass
class SovereignConfig:
    """Describes one sovereign deployment request."""
    agent_id: str
    server_ids: list[str]                        # e.g. ["gmail", "google_sheets"]
    sse_port: int = 8765                         # local port the MCP bridge listens on
    sse_path: str = "/mcp"                       # SSE endpoint path
    dashboard_origin: str = "https://app.agenticmind.com"  # allowed CORS origin
    client_label: Optional[str] = None          # friendly name shown in the guide
    env_vars: dict[str, str] = field(default_factory=dict)  # pre-filled env hints


# ---------------------------------------------------------------------------
# Layman install guide text
# ---------------------------------------------------------------------------

_PRIVACY_GUIDE_HEADER = (
    "Your data stays on YOUR machine. Agentic Mind never uploads your files or "
    "credentials to any cloud. The co-worker reads what it needs locally and sends "
    "only the final result back to your dashboard."
)

_ONE_COMMAND = "docker compose -f agentic-mind-local.yml up -d"

_VERIFY_HINT = (
    "Once the command finishes, click 'Verify Connection' in the dashboard. "
    "You will see a Privacy Shield icon confirming your local server is live."
)


# ---------------------------------------------------------------------------
# InstallerGenerator
# ---------------------------------------------------------------------------

class InstallerGenerator:
    """
    Generates config.json and docker-compose.yml for a sovereign (client-side)
    MCP deployment.  Both artefacts are returned as strings — the API layer
    decides how to deliver them (download, inline, etc.).
    """

    def generate(self, cfg: SovereignConfig) -> dict:
        """
        Returns a dict with:
          - config_json:        str  (contents of config.json)
          - docker_compose_yml: str  (contents of docker-compose.yml)
          - install_guide:      dict (layman-friendly UI copy)
          - one_command:        str  (the single command to run)
          - verify_url:         str  (the SSE health URL we will ping)
        """
        config_json    = self._build_config(cfg)
        compose_yml    = self._build_compose(cfg)
        install_guide  = self._build_guide(cfg)
        verify_url     = f"http://localhost:{cfg.sse_port}{cfg.sse_path}/health"

        return {
            "config_json":        json.dumps(config_json, indent=2),
            "docker_compose_yml": compose_yml,
            "install_guide":      install_guide,
            "one_command":        _ONE_COMMAND,
            "verify_url":         verify_url,
            "sse_url":            f"http://localhost:{cfg.sse_port}{cfg.sse_path}",
        }

    # ------------------------------------------------------------------
    # config.json
    # ------------------------------------------------------------------

    def _build_config(self, cfg: SovereignConfig) -> dict:
        servers = {}
        for sid in cfg.server_ids:
            preset = WELL_KNOWN_SERVERS.get(sid, {})
            servers[sid] = {
                "transport": "sse",
                "description": preset.get("description", ""),
                "env_hint": self._env_hints(sid),
            }

        return {
            "agent_id":        cfg.agent_id,
            "sovereign_mode":  True,
            "sse_port":        cfg.sse_port,
            "sse_path":        cfg.sse_path,
            "dashboard_origin": cfg.dashboard_origin,
            "servers":         servers,
            "data_policy": {
                "upload_to_cloud":    False,
                "local_execution":    True,
                "audit_log_locally":  True,
            },
        }

    # ------------------------------------------------------------------
    # docker-compose.yml
    # ------------------------------------------------------------------

    def _build_compose(self, cfg: SovereignConfig) -> str:
        service_blocks = []

        for sid in cfg.server_ids:
            preset  = WELL_KNOWN_SERVERS.get(sid, {})
            cmd     = preset.get("command", ["npx", "-y", f"@modelcontextprotocol/server-{sid}"])
            cmd_str = " ".join(cmd)
            env_hints = self._env_hints(sid)
            env_lines = "\n".join(
                f"      - {k}=${{{{ {k} }}}}"   # double-brace for literal in f-string
                for k in env_hints
            ).replace("{{", "{").replace("}}", "}")

            block = textwrap.dedent(f"""\
              {sid}-mcp:
                image: node:20-alpine
                working_dir: /app
                command: sh -c "{cmd_str}"
                environment:
{textwrap.indent(env_lines, '  ') if env_lines else '      []'}
                restart: unless-stopped
                labels:
                  - "agentic-mind.server={sid}"
                  - "agentic-mind.sovereign=true"
            """)
            service_blocks.append(block)

        # SSE bridge service — thin reverse-proxy that exposes all MCP servers
        # on a single SSE endpoint the dashboard connects to.
        bridge_envs = "\n".join(
            f"      - MCP_SERVER_{i}={sid}"
            for i, sid in enumerate(cfg.server_ids)
        )
        bridge_block = textwrap.dedent(f"""\
          agentic-bridge:
            image: node:20-alpine
            working_dir: /app
            command: >
              sh -c "npx -y @agenticmind/local-bridge
              --port {cfg.sse_port}
              --path {cfg.sse_path}
              --origin {cfg.dashboard_origin}
              --servers {','.join(cfg.server_ids)}"
            ports:
              - "{cfg.sse_port}:{cfg.sse_port}"
            environment:
{textwrap.indent(bridge_envs, '  ')}
            depends_on:
{chr(10).join(f'              - {sid}-mcp' for sid in cfg.server_ids)}
            restart: unless-stopped
            labels:
              - "agentic-mind.role=bridge"
              - "agentic-mind.sovereign=true"
        """)
        service_blocks.append(bridge_block)

        services_yaml = "\n".join(service_blocks)

        header = textwrap.dedent(f"""\
            # ============================================================
            # Agentic Mind — Sovereign Local MCP Stack
            # Agent: {cfg.agent_id}
            # Servers: {', '.join(cfg.server_ids)}
            #
            # Your data NEVER leaves this machine.
            # Start: docker compose -f agentic-mind-local.yml up -d
            # Stop:  docker compose -f agentic-mind-local.yml down
            # ============================================================
            version: "3.9"
            services:
        """)

        env_section = self._build_env_file_hint(cfg)
        return header + textwrap.indent(services_yaml, "  ") + "\n" + env_section

    def _build_env_file_hint(self, cfg: SovereignConfig) -> str:
        all_keys: list[str] = []
        for sid in cfg.server_ids:
            all_keys.extend(self._env_hints(sid).keys())
        if not all_keys:
            return ""
        lines = ["# --- Create a .env file in the same folder with your credentials ---"]
        lines += [f"# {k}=your_{k.lower()}_here" for k in all_keys]
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Layman install guide
    # ------------------------------------------------------------------

    def _build_guide(self, cfg: SovereignConfig) -> dict:
        label = cfg.client_label or "your computer"
        server_list = [
            WELL_KNOWN_SERVERS.get(sid, {}).get("display_label", sid.replace("_", " ").title())
            for sid in cfg.server_ids
        ]
        connected_text = " and ".join(server_list) if server_list else "your local data sources"

        steps = [
            {
                "step": 1,
                "icon": "download",
                "title": "Download the installer file",
                "detail": "Save 'agentic-mind-local.yml' to any folder on your computer.",
            },
            {
                "step": 2,
                "icon": "terminal",
                "title": "Run 1 command",
                "detail": f"Open Terminal (or Command Prompt) in that folder and run:",
                "command": _ONE_COMMAND,
                "copy_button": True,
            },
            {
                "step": 3,
                "icon": "shield",
                "title": "Verify your Privacy Shield",
                "detail": (
                    f"Come back here and click 'Verify Connection'. "
                    f"You will see a green Privacy Shield confirming that {connected_text} "
                    f"on {label} is connected — and your data stays there."
                ),
            },
        ]

        return {
            "headline": "Connect your private data — nothing leaves your machine",
            "privacy_statement": _PRIVACY_GUIDE_HEADER,
            "steps": steps,
            "verify_hint": _VERIFY_HINT,
            "one_command": _ONE_COMMAND,
            "what_stays_local": [
                "Your files and documents",
                "Your email credentials",
                "Your spreadsheet data",
                "All intermediate processing",
            ],
            "what_is_shared": [
                "The final result or report only",
                "No raw file contents",
                "No credentials",
            ],
        }

    # ------------------------------------------------------------------
    # Env var hints per server
    # ------------------------------------------------------------------

    @staticmethod
    def _env_hints(server_id: str) -> dict[str, str]:
        hints = {
            "gmail": {
                "GMAIL_CLIENT_ID":     "Your Google OAuth Client ID",
                "GMAIL_CLIENT_SECRET": "Your Google OAuth Client Secret",
                "GMAIL_REFRESH_TOKEN": "Your Gmail refresh token",
            },
            "google_sheets": {
                "GOOGLE_CLIENT_ID":     "Your Google OAuth Client ID",
                "GOOGLE_CLIENT_SECRET": "Your Google OAuth Client Secret",
                "GOOGLE_REFRESH_TOKEN": "Your Google refresh token",
            },
            "slack": {
                "SLACK_BOT_TOKEN":      "Your Slack Bot Token (xoxb-...)",
                "SLACK_TEAM_ID":        "Your Slack Workspace ID",
            },
        }
        return hints.get(server_id, {})
