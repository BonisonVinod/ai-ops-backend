"""
Agentic Factory Composer — LangGraph StateMachine

Consumes an analysis report (from the SOP Analyzer) and dynamically stitches
together a LangGraph StateMachine by selecting the right Tools and Knowledge
context for the task. Every thread is persisted in SqliteSaver.

Full flow:
  START
    → ingest_analysis        # parse the analysis report, extract task type
    → load_knowledge         # KnowledgeRouter injects domain rules into state
    → plan_actions           # LLM decides which tools to call and in what order
    → execute_tools          # runs each planned tool call sequentially
    → human_interrupt        # ALWAYS fires before: code execution, final calculations,
                             #   or when knowledge rules say human_review_required
    → synthesize             # final report with domain rules + tool results + human feedback
    → END
"""

import os
import json
import uuid
from typing import TypedDict, Optional, Annotated
from operator import add

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt

from app.engine.tools import (
    browser_search,
    extract_document,
    read_csv_as_json,
    execute_python,
    generate_code,
)
from app.engine.tools.mcp_manager import get_mcp_manager, layman_name
from app.engine.knowledge.knowledge_router import KnowledgeRouter, KnowledgeContext
from app.engine.knowledge.accounting_router import AccountingRouter
from app.engine.knowledge.compliance_router import ComplianceRouter


# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------

class FactoryState(TypedDict):
    # Input
    task_input: str
    analysis_report: Optional[dict]          # output from sop_analyzer, if available
    thread_id: str

    # Knowledge & domain
    knowledge_domain: Optional[str]
    knowledge_context: Optional[dict]        # serialized KnowledgeContext
    domain_analysis: Optional[dict]
    functional_purpose: Optional[str]        # human-readable intent (e.g. "Customer Operations")

    # Action planning
    planned_actions: list[str]               # ordered list of tool names to invoke
    planned_action_inputs: list[str]         # corresponding input for each tool
    current_action_index: int

    # Execution
    tool_results: Annotated[list[str], add]  # accumulated tool outputs
    human_review_required: bool
    high_risk_action_pending: Optional[str]  # which action triggered the interrupt

    # MCP integrations
    required_mcp_servers: list[str]        # server IDs flagged by KnowledgeRouter
    mcp_tool_results: Annotated[list[str], add]

    # Human-in-the-loop
    human_feedback: Optional[str]

    # Output
    final_output: Optional[str]
    frontend_payload: Optional[dict]         # user-facing card data (summary, category, pro_tip)
    messages: Annotated[list[BaseMessage], add]
    error: Optional[str]


# ---------------------------------------------------------------------------
# Module-level singletons (avoids re-init on every call)
# ---------------------------------------------------------------------------

_llm = None
_knowledge_router = None
_accounting_router = None
_compliance_router = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)
    return _llm


def _get_knowledge_router() -> KnowledgeRouter:
    global _knowledge_router
    if _knowledge_router is None:
        _knowledge_router = KnowledgeRouter()
    return _knowledge_router


def _get_accounting_router() -> AccountingRouter:
    global _accounting_router
    if _accounting_router is None:
        _accounting_router = AccountingRouter()
    return _accounting_router


def _get_compliance_router() -> ComplianceRouter:
    global _compliance_router
    if _compliance_router is None:
        _compliance_router = ComplianceRouter()
    return _compliance_router


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_PLAN_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are an Agentic Factory planner. Given a task and its domain analysis, "
        "decide which tools to invoke in sequence. Available tools:\n"
        "  - browser_search: web search for reference information\n"
        "  - extract_document: extract text from PDF/DOCX/TXT/CSV file path\n"
        "  - read_csv_as_json: read a CSV file and return JSON rows\n"
        "  - execute_python: run Python code for calculations/analysis\n"
        "  - generate_code: write Python code for a described task\n\n"
        "MCP tools (use when the server is listed in required_mcp_servers):\n"
        "  - mcp:gmail:send_email — Send Official Email\n"
        "  - mcp:gmail:list_messages — View Inbox Messages\n"
        "  - mcp:google_sheets:append_values — Add Rows to Spreadsheet\n"
        "  - mcp:google_sheets:get_values — Read Spreadsheet Data\n"
        "  - mcp:slack:post_message — Send a Slack Message\n"
        "MCP tool names follow the pattern: mcp:<server_id>:<tool_name>\n\n"
        "Return ONLY a JSON object with:\n"
        "  tools: list of tool names in execution order\n"
        "  inputs: list of input strings (or JSON objects) for each tool (same order)\n"
        "Example: {{\"tools\": [\"read_csv_as_json\", \"mcp:google_sheets:append_values\"], "
        "\"inputs\": [\"/path/to/file.csv\", \"{{\\\"spreadsheetId\\\": \\\"abc\\\", \\\"range\\\": \\\"Sheet1!A1\\\", \\\"values\\\": []}}\"]}}",
    ),
    (
        "human",
        "Task: {task}\n\nDomain: {domain}\n\nRequired MCP Servers: {mcp_servers}\n\n"
        "Knowledge Rules Summary:\n{rules_summary}\n\nAnalysis Report:\n{analysis_report}",
    ),
])

_SYNTHESIZE_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a senior AI Operations analyst at Agentic Mind. "
        "Produce a final structured audit/analysis report. "
        "Incorporate the domain compliance rules, all tool outputs, and any human feedback. "
        "Flag all items requiring further human action. Be precise and actionable.",
    ),
    (
        "human",
        "Task: {task}\n\n"
        "Domain Rules Applied:\n{rules}\n\n"
        "Tool Execution Results:\n{tool_results}\n\n"
        "Human Review Feedback: {human_feedback}\n\n"
        "Write the final report now.",
    ),
])

_HIGH_RISK_TOOLS = {"execute_python", "generate_code"}


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

_CUSTOMER_OPS_SIGNALS = {
    "troubleshooting", "troubleshoot", "escalation", "escalate",
    "diagnostic", "diagnose", "sop", "support", "helpdesk", "runbook",
    "playbook", "triage", "incident response", "call script",
}

_FUNCTIONAL_PURPOSE_MAP = {
    "customer_operations": "Customer Operations",
    "accounting": "Finance & Accounting",
    "it_compliance": "IT Compliance & Security",
    "hr_compliance": "HR & People Ops",
    "general": "General Workflow Automation",
}


def ingest_analysis(state: FactoryState) -> dict:
    """Parse the incoming task and any attached analysis report."""
    task = state["task_input"]
    task_lower = task.lower()
    report = state.get("analysis_report") or {}

    # Determine domain — customer_operations takes priority when support signals detected
    domain_hint = "general"
    functional_purpose = "General Workflow Automation"

    if any(sig in task_lower for sig in _CUSTOMER_OPS_SIGNALS):
        domain_hint = "customer_operations"
        functional_purpose = "Customer Operations"
    elif "account" in task_lower or "audit" in task_lower or "financial" in task_lower:
        domain_hint = "accounting"
        functional_purpose = "Finance & Accounting"
    elif "compliance" in task_lower or "legal" in task_lower:
        domain_hint = "it_compliance"
        functional_purpose = "IT Compliance & Security"
    elif report:
        sop_type = report.get("type", "").lower()
        if sop_type in ("sop", "jd"):
            domain_hint = "accounting" if AccountingRouter.can_handle(task) else "general"
            functional_purpose = _FUNCTIONAL_PURPOSE_MAP.get(domain_hint, "General Workflow Automation")

    return {
        "knowledge_domain": domain_hint,
        "functional_purpose": functional_purpose,
        "messages": [HumanMessage(content=f"[Task ingested] {task[:200]} — Functional Purpose: {functional_purpose}")],
    }


def load_knowledge(state: FactoryState) -> dict:
    """Load domain-specific rules via KnowledgeRouter and run specialist domain analysis."""
    task = state["task_input"]
    domain = state.get("knowledge_domain", "general")

    # Get structured knowledge context
    kr = _get_knowledge_router()
    ctx = kr.get_context(task)
    ctx_dict = ctx.to_dict()

    # Run specialist router for richer analysis
    domain_analysis: dict = {}
    if domain == "accounting" or AccountingRouter.can_handle(task):
        domain_analysis = _get_accounting_router().route(task)
    elif domain in ("it_compliance", "compliance") or ComplianceRouter.can_handle(task):
        domain_analysis = _get_compliance_router().route(task)

    # Merge human_review_required from both sources
    specialist_requires_review = False
    if domain_analysis.get("status") == "success":
        a = domain_analysis.get("analysis", {})
        if isinstance(a, dict):
            specialist_requires_review = bool(a.get("human_review_required", False))

    human_required = ctx.human_review_required or specialist_requires_review

    return {
        "knowledge_context": ctx_dict,
        "domain_analysis": domain_analysis,
        "human_review_required": human_required,
        "required_mcp_servers": ctx.required_mcp_servers,
        "messages": [AIMessage(content=f"[Knowledge loaded] Domain: {', '.join(ctx.domains)}, Rules: {len(ctx.applicable_rules)}, Human required: {human_required}, MCP: {ctx.required_mcp_servers}")],
    }


def plan_actions(state: FactoryState) -> dict:
    """LLM selects and sequences tool calls based on the task and domain context."""
    task = state["task_input"]
    domain = state.get("knowledge_domain", "general")
    ctx = state.get("knowledge_context", {})
    report = state.get("analysis_report", {})

    rules_summary = ctx.get("system_prompt_injection", "No specific rules loaded.")[:1000]

    try:
        mcp_servers = state.get("required_mcp_servers") or []
        llm = _get_llm()
        chain = _PLAN_PROMPT | llm
        response = chain.invoke({
            "task": task,
            "domain": domain,
            "mcp_servers": ", ".join(mcp_servers) if mcp_servers else "none",
            "rules_summary": rules_summary,
            "analysis_report": json.dumps(report, indent=2)[:2000] if report else "None",
        })

        # Parse JSON plan — handle markdown-fenced responses
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        plan = json.loads(content)

        tools = plan.get("tools", [])
        inputs = plan.get("inputs", [])

        # Pad inputs if shorter than tools list
        while len(inputs) < len(tools):
            inputs.append(task)

    except Exception as e:
        # Fallback: safe default plan
        tools = ["read_csv_as_json"] if ".csv" in task.lower() else ["browser_search"]
        inputs = [task]

    return {
        "planned_actions": tools,
        "planned_action_inputs": inputs,
        "current_action_index": 0,
        "messages": [AIMessage(content=f"[Plan] Tools to invoke: {tools}")],
    }


def _is_sovereign_server(server_id: str) -> bool:
    """Return True if the registered server is in sovereign (local) mode."""
    try:
        mgr = get_mcp_manager()
        s = mgr._servers.get(server_id)
        return bool(s and s.sovereign)
    except Exception:
        return False


def _invoke_mcp_tool(tool_name: str, tool_input: str) -> str:
    """
    Dispatch an MCP tool call. tool_name format: mcp:<server_id>:<mcp_tool_name>
    tool_input may be a JSON string (dict of arguments) or a plain string.
    Returns a string result for state accumulation.

    For sovereign (local) servers the result is prefixed with [LOCAL EXECUTION]
    so the Live Terminal can surface a data-sovereignty audit line.
    """
    parts = tool_name.split(":", 2)
    if len(parts) != 3:
        return f"[{tool_name}] Invalid MCP tool format — expected mcp:<server_id>:<tool>"
    _, server_id, mcp_tool = parts

    try:
        arguments = json.loads(tool_input) if tool_input.strip().startswith("{") else {"input": tool_input}
    except json.JSONDecodeError:
        arguments = {"input": tool_input}

    display = layman_name(mcp_tool)
    manager = get_mcp_manager()

    if not manager.is_registered(server_id):
        return (
            f"[MCP: {display}] Server '{server_id}' is not connected. "
            "The frontend should prompt the user to authorize this connector before the agent can use it."
        )

    sovereign = _is_sovereign_server(server_id)
    locality_tag = "[LOCAL EXECUTION] " if sovereign else ""

    # Emit a data-sovereignty audit line for file/document arguments
    audit_lines = []
    file_path_hint = arguments.get("path") or arguments.get("file") or arguments.get("spreadsheetId")
    if sovereign and file_path_hint:
        audit_lines.append(
            f"[LOCAL EXECUTION] Accessing local resource: {file_path_hint} — "
            "Data not uploaded to cloud."
        )

    try:
        result = manager.call_tool(server_id, mcp_tool, arguments)
        prefix = f"{locality_tag}[MCP: {display}]"
        audit_prefix = "\n".join(audit_lines) + "\n" if audit_lines else ""
        return f"{audit_prefix}{prefix}\n{str(result)[:3000]}"
    except Exception as e:
        return f"{locality_tag}[MCP: {display}] Error: {str(e)}"


def execute_tools(state: FactoryState) -> dict:
    """Execute all planned tool calls sequentially, collecting results.
    Supports both built-in tools and MCP tools (prefix: mcp:<server>:<tool>).
    """
    tools_list = state.get("planned_actions", [])
    inputs_list = state.get("planned_action_inputs", [])

    TOOL_MAP = {
        "browser_search": browser_search,
        "extract_document": extract_document,
        "read_csv_as_json": read_csv_as_json,
        "execute_python": execute_python,
        "generate_code": generate_code,
    }

    results = []
    mcp_results = []
    pending_high_risk = None

    for i, (tool_name, tool_input) in enumerate(zip(tools_list, inputs_list)):
        # MCP tool — route to MCPManager
        if tool_name.startswith("mcp:"):
            result = _invoke_mcp_tool(tool_name, tool_input)
            mcp_results.append(result)
            results.append(result)
            continue

        # Flag high-risk tools — these will be interrupted before execution
        if tool_name in _HIGH_RISK_TOOLS:
            pending_high_risk = tool_name
            results.append(f"[{tool_name}] PENDING HUMAN APPROVAL — input: {tool_input[:300]}")
            break

        tool_fn = TOOL_MAP.get(tool_name)
        if not tool_fn:
            results.append(f"[{tool_name}] Unknown tool — skipped")
            continue

        try:
            # Emit a LOCAL EXECUTION audit line for file-reading tools
            local_tag = ""
            if tool_name in ("extract_document", "read_csv_as_json"):
                local_tag = (
                    f"[LOCAL EXECUTION] Reading local file: {tool_input[:200]} — "
                    "Data not uploaded to cloud.\n"
                )
            result = tool_fn.invoke(tool_input)
            results.append(f"{local_tag}[{tool_name}]\n{str(result)[:3000]}")
        except Exception as e:
            results.append(f"[{tool_name}] Error: {str(e)}")

    return {
        "tool_results": results,
        "mcp_tool_results": mcp_results,
        "high_risk_action_pending": pending_high_risk,
        "current_action_index": len(results),
        "messages": [AIMessage(content=f"[Tools executed] {len(results)} results collected ({len(mcp_results)} MCP)")],
    }


def human_interrupt_node(state: FactoryState) -> dict:
    """
    Pause point for human review. Fires when:
    - knowledge rules require human_review_required = true, OR
    - a high-risk tool (execute_python, generate_code) is about to run
    """
    ctx = state.get("knowledge_context", {})
    tool_results_so_far = state.get("tool_results", [])
    pending_action = state.get("high_risk_action_pending")
    domain_analysis = state.get("domain_analysis", {})

    interrupt_payload = {
        "message": "⚠️ Human review required before proceeding.",
        "thread_id": state["thread_id"],
        "task": state["task_input"],
        "domain": state.get("knowledge_domain"),
        "applicable_rules": [
            r["id"] for r in ctx.get("applicable_rules", [])
            if r.get("human_approval_required")
        ],
        "tool_results_so_far": [r[:500] for r in tool_results_so_far],
        "pending_high_risk_action": pending_action,
        "domain_analysis_summary": str(domain_analysis)[:500],
        "instructions": (
            "Review the tool results and domain analysis above. "
            "Reply with 'approved' to continue, 'rejected: <reason>' to stop, "
            "or 'approved with changes: <notes>' to add feedback."
        ),
    }

    feedback = interrupt(interrupt_payload)

    return {
        "human_feedback": str(feedback) if feedback else "approved",
        "messages": [HumanMessage(content=f"[Human review] {str(feedback)[:200]}")],
    }


def execute_high_risk_tools(state: FactoryState) -> dict:
    """Execute high-risk tools that were held for human approval."""
    feedback = state.get("human_feedback", "").lower()
    if feedback.startswith("rejected"):
        return {
            "tool_results": [f"[HIGH-RISK TOOLS] Rejected by human reviewer. Reason: {feedback}"],
            "messages": [AIMessage(content="[High-risk execution skipped — rejected by human]")],
        }

    tools_list = state.get("planned_actions", [])
    inputs_list = state.get("planned_action_inputs", [])
    start_idx = state.get("current_action_index", 0)

    TOOL_MAP = {
        "execute_python": execute_python,
        "generate_code": generate_code,
    }

    results = []
    for tool_name, tool_input in zip(tools_list[start_idx:], inputs_list[start_idx:]):
        tool_fn = TOOL_MAP.get(tool_name)
        if not tool_fn:
            continue
        try:
            result = tool_fn.invoke(tool_input)
            results.append(f"[{tool_name}] (post-approval)\n{str(result)[:3000]}")
        except Exception as e:
            results.append(f"[{tool_name}] Error: {str(e)}")

    return {
        "tool_results": results,
        "messages": [AIMessage(content=f"[High-risk tools executed post-approval] {len(results)} results")],
    }


_SUPPORT_SOP_PRO_TIPS = [
    "Connect an Email Auto-Response agent to handle common queries before human escalation.",
    "Sync resolved tickets to a Knowledge Base so future issues auto-resolve without agent effort.",
    "Add a Sentiment Detector to auto-escalate frustrated customers before they churn.",
    "Route repeat issues to a dedicated FAQ bot to cut ticket volume by up to 40%.",
]

_DOMAIN_CATEGORY_LABELS = {
    "customer_operations": "Workflow Automation Blueprint — Customer Operations",
    "accounting": "Workflow Automation Blueprint — Finance & Accounting",
    "it_compliance": "Workflow Automation Blueprint — IT Compliance",
    "hr_compliance": "Workflow Automation Blueprint — HR & People Ops",
    "general": "Workflow Automation Blueprint",
}


def _build_frontend_payload(state: FactoryState, report_text: str) -> dict:
    domain = state.get("knowledge_domain", "general")
    functional_purpose = state.get("functional_purpose", "General Workflow Automation")
    task = state.get("task_input", "")
    report = state.get("analysis_report") or {}
    ctx = state.get("knowledge_context") or {}

    # Count steps from planned actions or analysis report
    step_count = len(state.get("planned_actions", []))
    if step_count == 0:
        step_count = report.get("step_count") or report.get("total_tasks") or 0
    step_prefix = f"Automating a {step_count}-step " if step_count > 1 else "Automating a "

    # Build a human-readable summary line
    summary = f"{step_prefix}{functional_purpose} Workflow"

    # Category label (no tech jargon)
    category = _DOMAIN_CATEGORY_LABELS.get(domain, "Workflow Automation Blueprint")

    # Pro-Tip: surface bundled automations for support/customer-ops SOPs
    pro_tip = None
    if domain == "customer_operations":
        import hashlib
        # Deterministically pick a tip based on task text so it stays stable per task
        idx = int(hashlib.md5(task.encode()).hexdigest(), 16) % len(_SUPPORT_SOP_PRO_TIPS)
        pro_tip = f"Pro-Tip: {_SUPPORT_SOP_PRO_TIPS[idx]}"

    return {
        "summary": summary,
        "category": category,
        "functional_purpose": functional_purpose,
        "pro_tip": pro_tip,
        "domain": domain,
        "step_count": step_count,
    }


def synthesize(state: FactoryState) -> dict:
    """Produce the final structured report."""
    ctx = state.get("knowledge_context", {})
    rules_text = ctx.get("system_prompt_injection", "No domain rules applied.")[:3000]
    tool_results = state.get("tool_results", [])
    tool_results_text = "\n\n".join(tool_results) if tool_results else "No tool results."
    human_feedback = state.get("human_feedback", "No human review was performed.")

    try:
        llm = _get_llm()
        chain = _SYNTHESIZE_PROMPT | llm
        response = chain.invoke({
            "task": state["task_input"],
            "rules": rules_text,
            "tool_results": tool_results_text[:4000],
            "human_feedback": human_feedback,
        })
        output = response.content
    except Exception as e:
        output = (
            f"Synthesis failed: {str(e)}\n\n"
            f"Raw tool results:\n{tool_results_text[:2000]}"
        )

    frontend_payload = _build_frontend_payload(state, output)

    return {
        "final_output": output,
        "frontend_payload": frontend_payload,
        "messages": [AIMessage(content=f"[Final report generated] {len(output)} chars")],
    }


# ---------------------------------------------------------------------------
# Conditional routing
# ---------------------------------------------------------------------------

def _should_interrupt(state: FactoryState) -> str:
    if state.get("human_review_required") or state.get("high_risk_action_pending"):
        return "human_interrupt"
    return "synthesize"


def _after_interrupt(state: FactoryState) -> str:
    if state.get("high_risk_action_pending"):
        return "execute_high_risk_tools"
    return "synthesize"


# ---------------------------------------------------------------------------
# Graph definition (uncompiled — checkpointer injected at runtime)
# ---------------------------------------------------------------------------

def _build_graph_definition() -> StateGraph:
    """Returns an uncompiled StateGraph. Compile with a checkpointer inside a context manager."""
    builder = StateGraph(FactoryState)

    builder.add_node("ingest_analysis", ingest_analysis)
    builder.add_node("load_knowledge", load_knowledge)
    builder.add_node("plan_actions", plan_actions)
    builder.add_node("execute_tools", execute_tools)
    builder.add_node("human_interrupt", human_interrupt_node)
    builder.add_node("execute_high_risk_tools", execute_high_risk_tools)
    builder.add_node("synthesize", synthesize)

    builder.add_edge(START, "ingest_analysis")
    builder.add_edge("ingest_analysis", "load_knowledge")
    builder.add_edge("load_knowledge", "plan_actions")
    builder.add_edge("plan_actions", "execute_tools")
    builder.add_conditional_edges("execute_tools", _should_interrupt, {
        "human_interrupt": "human_interrupt",
        "synthesize": "synthesize",
    })
    builder.add_conditional_edges("human_interrupt", _after_interrupt, {
        "execute_high_risk_tools": "execute_high_risk_tools",
        "synthesize": "synthesize",
    })
    builder.add_edge("execute_high_risk_tools", "synthesize")
    builder.add_edge("synthesize", END)

    return builder


def build_factory_graph(db_path: str = "factory_checkpoints.db"):
    """
    Returns (builder, checkpointer_cm) where checkpointer_cm is a context manager.

    Usage:
        builder, saver_cm = build_factory_graph()
        with saver_cm as checkpointer:
            graph = builder.compile(checkpointer=checkpointer, interrupt_before=["human_interrupt"])
            result = graph.invoke(state, config)
    """
    builder = _build_graph_definition()
    saver_cm = SqliteSaver.from_conn_string(db_path)
    return builder, saver_cm


def _make_initial_state(
    task: str,
    thread_id: str,
    analysis_report: Optional[dict] = None,
) -> dict:
    return {
        "task_input": task,
        "analysis_report": analysis_report,
        "thread_id": thread_id,
        "knowledge_domain": None,
        "functional_purpose": None,
        "knowledge_context": None,
        "domain_analysis": None,
        "planned_actions": [],
        "planned_action_inputs": [],
        "current_action_index": 0,
        "tool_results": [],
        "required_mcp_servers": [],
        "mcp_tool_results": [],
        "human_review_required": False,
        "high_risk_action_pending": None,
        "human_feedback": None,
        "final_output": None,
        "frontend_payload": None,
        "messages": [],
        "error": None,
    }


def run_factory(
    task: str,
    thread_id: Optional[str] = None,
    db_path: str = "factory_checkpoints.db",
    analysis_report: Optional[dict] = None,
    human_feedback: Optional[str] = None,
) -> dict:
    """
    Main entry point for the Agentic Factory.

    First call: pass task + thread_id. If human review is required, the graph
    pauses and returns a snapshot (check result.get('__interrupt__')).

    Resume call: pass the same thread_id + human_feedback to continue from the
    human_interrupt node.
    """
    if thread_id is None:
        thread_id = str(uuid.uuid4())

    builder, saver_cm = build_factory_graph(db_path)
    config = {"configurable": {"thread_id": thread_id}}

    with saver_cm as checkpointer:
        graph = builder.compile(
            checkpointer=checkpointer,
            interrupt_before=["human_interrupt"],
        )
        if human_feedback is not None:
            graph.update_state(config, {"human_feedback": human_feedback})
            result = graph.invoke(None, config)
        else:
            initial = _make_initial_state(task, thread_id, analysis_report)
            result = graph.invoke(initial, config)

    return result
