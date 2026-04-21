# MCP Integration Guide

This document describes how the Model Context Protocol (MCP) layer is wired into the Agentic Factory.

---

## Architecture Overview

```
KnowledgeRouter (keyword scan)
    → required_mcp_servers: ["gmail", "google_sheets", ...]
          ↓
/ai/build endpoint
    → connectors: [ { server_id, button_label, icon, description } ]
          ↓
Frontend renders "Connect Gmail" / "Connect Spreadsheet" buttons
          ↓
MCPManager (app/engine/tools/mcp_manager.py)
    → registers server on user authorization
          ↓
Composer execute_tools node
    → dispatches mcp:<server_id>:<tool_name> calls via MCPManager
```

---

## Files

| File | Role |
|---|---|
| `app/engine/tools/mcp_manager.py` | Core MCP client — registration, discovery, execution |
| `app/engine/knowledge/knowledge_router.py` | Keyword-based MCP server detection |
| `app/api/routes/ai_ops_routes.py` | `/ai/build` endpoint — adds `connectors` array |
| `app/engine/composer.py` | `execute_tools` node — dispatches MCP tool calls |

---

## Supported MCP Servers

### Gmail

**Triggers:** `email`, `e-mail`, `customer contact`, `send mail`, `follow up`, `correspondence`

**Well-known tools (layman names):**

| Raw MCP name | Displayed as |
|---|---|
| `send_mime_message` | Send Official Email |
| `send_email` | Send Official Email |
| `list_messages` | View Inbox Messages |
| `get_message` | Read an Email |
| `search_messages` | Search Emails |
| `create_draft` | Draft an Email |
| `reply_to_message` | Reply to an Email |

### Google Sheets

**Triggers:** `spreadsheet`, `data tracking`, `ledger`, `tracker`, `log entries`, `data entry`

| Raw MCP name | Displayed as |
|---|---|
| `append_values` | Add Rows to Spreadsheet |
| `update_values` | Update Spreadsheet Data |
| `get_values` | Read Spreadsheet Data |
| `create_spreadsheet` | Create a New Spreadsheet |
| `batch_update` | Bulk Update Spreadsheet |

### Slack

**Triggers:** `slack`, `team notification`, `channel alert`, `notify team`, `post to channel`

| Raw MCP name | Displayed as |
|---|---|
| `post_message` | Send a Slack Message |
| `send_message` | Send a Slack Message |
| `list_channels` | List Slack Channels |
| `get_channel_history` | Read Channel Messages |
| `upload_file` | Share a File on Slack |

---

## Registering a Server at Runtime

```python
from app.engine.tools.mcp_manager import get_mcp_manager

manager = get_mcp_manager()

# stdio transport (local Node.js process)
manager.register(
    "gmail",
    transport="stdio",
    command=["npx", "-y", "@modelcontextprotocol/server-gmail"],
    env={"GMAIL_OAUTH_TOKEN": "<token>"},
)

# SSE transport (remote HTTP endpoint)
manager.register(
    "google_sheets",
    transport="sse",
    url="https://mcp.example.com/sheets",
    headers={"Authorization": "Bearer <token>"},
)
```

Registration is lazy — the process/connection is not opened until the first tool call.

---

## How the Frontend Should Use `connectors`

The `/ai/build` response now includes:

```json
{
  "status": "success",
  "agent_id": "cw-abc12345",
  "config": { ... },
  "connectors": [
    {
      "server_id": "gmail",
      "display_label": "Gmail",
      "button_label": "Connect Gmail",
      "icon": "mail",
      "description": "Send emails, read inbox, and manage drafts directly from the co-worker."
    },
    {
      "server_id": "google_sheets",
      "display_label": "Google Sheets",
      "button_label": "Connect Spreadsheet",
      "icon": "table",
      "description": "Read, append, and update spreadsheet data for tracking and reporting."
    }
  ]
}
```

**Rendering logic:** For each item in `connectors`, render a button using `button_label`. On click, open the OAuth / authorization flow for that server, then POST the resulting token to your backend so `MCPManager.register()` can be called with the credentials.

If `connectors` is an empty array, no integration buttons are shown.

---

## How Composer Invokes MCP Tools

The LLM planner in `plan_actions` selects tools using the format:

```
mcp:<server_id>:<mcp_tool_name>
```

Examples:
- `mcp:gmail:send_email`
- `mcp:google_sheets:append_values`
- `mcp:slack:post_message`

The `execute_tools` node detects the `mcp:` prefix and routes to `MCPManager.call_tool()`. If the server is not yet registered (user hasn't connected), it returns a friendly message instructing the frontend to prompt the user to authorize that connector.

---

## Adding a New MCP Server

1. Add keyword triggers to `MCP_SERVER_KEYWORDS` in `knowledge_router.py`.
2. Add a preset entry to `WELL_KNOWN_SERVERS` in `mcp_manager.py`.
3. Add layman name mappings to `_LAYMAN_NAMES` in `mcp_manager.py`.
4. No changes to `composer.py` are needed — the `mcp:` prefix routing is generic.
