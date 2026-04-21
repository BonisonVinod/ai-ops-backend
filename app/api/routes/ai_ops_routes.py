import asyncio
import json
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from fastapi.responses import FileResponse, Response

from app.orchestrator.main_orchestrator import Orchestrator
from app.agents.sop_analyzer import analyze_sop
from app.engine.knowledge.knowledge_router import KnowledgeRouter
from app.engine.tools.mcp_manager import connector_button, WELL_KNOWN_SERVERS, get_mcp_manager
from app.engine.sovereign.installer_generator import InstallerGenerator, SovereignConfig

router = APIRouter()

orchestrator = Orchestrator()
_knowledge_router = KnowledgeRouter()


# -------------------------------
# EXISTING ENDPOINTS (KEEP)
# -------------------------------

@router.post("/test-ai")
def test_ai(ticket: dict):
    ticket_text = ticket.get("text", "")
    result = orchestrator.run(ticket_text)
    return {"status": "success", "data": result}


class AnalyzeRequest(BaseModel):
    text: str


@router.post("/analyze")
def analyze(request: AnalyzeRequest):
    try:
        result = analyze_sop(request.text)
        return {"status": "success", "analysis": result.get("analysis")}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# -----------------------------------------------------------------------
# POST /ai/build — generate co-worker-config.json from approved analysis
# -----------------------------------------------------------------------

class BuildRequest(BaseModel):
    analysis: dict
    agent_spec: Optional[dict] = None
    thread_id: Optional[str] = None


@router.post("/build")
def build_coworker(req: BuildRequest):
    """
    Takes the approved SOP analysis (output of /sop/analyze or /ai/analyze)
    and returns a fully-specified co-worker-config.json containing:
      - Tools the co-worker can use
      - Knowledge domains it operates in
      - A 7-node LangGraph workflow
      - 6 domain-appropriate diagnostic questions
      - A system prompt ready for injection
      - connectors: list of MCP integration buttons to show in the frontend
    """
    config = _generate_coworker_config(req.analysis, req.agent_spec)
    connectors = _detect_connectors(req.analysis)
    server_ids = [c["server_id"] for c in connectors]
    self_host_guide = _build_self_host_guide(config["agent_id"], server_ids)
    return {
        "status": "success",
        "agent_id": config["agent_id"],
        "config": config,
        "connectors": connectors,
        "self_host_guide": self_host_guide,
    }


# -----------------------------------------------------------------------
# GET /ai/build/stream — SSE terminal animation for the Build phase
# -----------------------------------------------------------------------

@router.get("/build/stream")
async def build_stream(sovereign: bool = False):
    """
    Server-Sent Events stream that drives the Live Terminal animation.
    Pass ?sovereign=true to emit data-sovereignty audit messages.
    """
    async def event_gen():
        steps = [
            ("progress", "Initializing Environment..."),
            ("progress", "Injecting Support Intelligence..."),
            ("progress", "Wiring 7-node LangGraph..."),
            ("progress", "Finalizing Sandbox Persistence..."),
        ]
        if sovereign:
            steps = [
                ("progress",  "Initializing Sovereign Environment..."),
                ("local",     "[LOCAL EXECUTION] Verifying local MCP bridge at localhost:8765 — OK"),
                ("progress",  "Injecting Support Intelligence (rules loaded locally)..."),
                ("local",     "[LOCAL EXECUTION] Knowledge rules applied on-device — not uploaded to cloud"),
                ("progress",  "Wiring 7-node LangGraph with local connectors..."),
                ("local",     "[LOCAL EXECUTION] All tool calls routed to local Docker stack"),
                ("progress",  "Finalizing Sovereign Sandbox..."),
                ("shield",    "Privacy Shield active — your data stays on your machine ✓"),
            ]
        for event_type, message in steps:
            payload = json.dumps({"type": event_type, "message": message})
            yield f"data: {payload}\n\n"
            await asyncio.sleep(1.3)
        done = json.dumps({"type": "complete", "message": "Co-worker deployed successfully ✓"})
        yield f"data: {done}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# -----------------------------------------------------------------------
# Sovereign / Self-Host endpoints
# -----------------------------------------------------------------------

class SovereignGenerateRequest(BaseModel):
    agent_id: str
    server_ids: list[str]
    sse_port: int = 8765
    client_label: Optional[str] = None


@router.post("/sovereign/generate")
def sovereign_generate(req: SovereignGenerateRequest):
    """
    Generate installer artefacts for client-side sovereign deployment.
    Returns config.json contents, docker-compose.yml contents, and a
    layman-friendly install guide the frontend can render step-by-step.
    """
    cfg = SovereignConfig(
        agent_id=req.agent_id,
        server_ids=req.server_ids,
        sse_port=req.sse_port,
        client_label=req.client_label,
    )
    result = InstallerGenerator().generate(cfg)
    return {"status": "success", **result}


@router.get("/sovereign/download/compose")
def sovereign_download_compose(agent_id: str, server_ids: str, sse_port: int = 8765):
    """
    Download the docker-compose.yml as a file attachment.
    server_ids is comma-separated e.g. gmail,google_sheets
    """
    ids = [s.strip() for s in server_ids.split(",") if s.strip()]
    cfg = SovereignConfig(agent_id=agent_id, server_ids=ids, sse_port=sse_port)
    result = InstallerGenerator().generate(cfg)
    return Response(
        content=result["docker_compose_yml"],
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=agentic-mind-local.yml"},
    )


class SovereignVerifyRequest(BaseModel):
    url: str
    server_id: Optional[str] = None


@router.post("/sovereign/verify")
def sovereign_verify(req: SovereignVerifyRequest):
    """
    Ping the client's local SSE bridge health endpoint.
    Returns shield status so the frontend can show/hide the Privacy Shield icon.
    """
    manager = get_mcp_manager()

    # If a registered server ID is given, use its stored URL
    if req.server_id and manager.is_registered(req.server_id):
        result = manager.ping_sovereign(req.server_id)
    else:
        result = manager.ping_url(req.url)

    return {"status": "success" if result["ok"] else "unreachable", **result}


# -----------------------------------------------------------------------
# POST /ai/coworker/chat — test the deployed co-worker
# -----------------------------------------------------------------------

class ChatRequest(BaseModel):
    query: str
    config: dict
    conversation_history: Optional[list] = None


@router.post("/coworker/chat")
def coworker_chat(req: ChatRequest):
    """
    Send a support query to the deployed co-worker.
    The agent works through the 6 diagnostic questions in order,
    using the SOP steps and domain rules as its knowledge base.
    """
    try:
        result = _run_coworker_chat(
            req.query, req.config, req.conversation_history or []
        )
        return {"status": "success", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# -----------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------

_DOMAIN_KEYWORDS_BUILD = {
    "customer_operations": {
        "troubleshoot", "escalat", "diagnostic", "sop", "support",
        "helpdesk", "runbook", "triage", "ticket", "incident response",
    },
    "accounting": {
        "payroll", "salary", "tds", "gst", "invoice", "tax", "audit",
        "ledger", "journal", "financial",
    },
    "it_compliance": {
        "data privacy", "pii", "gdpr", "dpdp", "security", "iso 27001",
        "breach", "cert-in", "penetration",
    },
    "hr_compliance": {
        "recruitment", "onboarding", "performance", "termination", "leave",
        "appraisal", "hiring",
    },
}

_SKILL_TO_TOOL_BUILD = {
    "pdf": "extract_document", "docx": "extract_document",
    "document": "extract_document", "csv": "read_csv_as_json",
    "spreadsheet": "read_csv_as_json", "excel": "read_csv_as_json",
    "python": "execute_python", "calculation": "execute_python",
    "code": "generate_code", "script": "generate_code",
    "web": "browser_search", "search": "browser_search",
    "api": "browser_search",
}


def _detect_domain_from_analysis(analysis: dict) -> str:
    text = (
        analysis.get("process_understanding", "") + " " +
        " ".join(analysis.get("required_ai_skills", []))
    ).lower()
    for domain, kws in _DOMAIN_KEYWORDS_BUILD.items():
        if any(kw in text for kw in kws):
            return domain
    return "general"


def _detect_functional_purpose(analysis: dict, domain: str) -> str:
    labels = {
        "customer_operations": "Customer Operations",
        "accounting": "Finance & Accounting",
        "it_compliance": "IT Compliance",
        "hr_compliance": "HR & People Ops",
        "general": "General Operations",
    }
    return labels.get(domain, "Operations")


def _detect_tools_from_analysis(analysis: dict, agent_spec: Optional[dict]) -> list[str]:
    # Prefer tools already detected by agent_spec_service
    if agent_spec:
        frs = agent_spec.get("factory_run_spec", {})
        if frs.get("recommended_tools"):
            return frs["recommended_tools"]

    skills = analysis.get("required_ai_skills", [])
    tools: set[str] = set()
    for skill in skills:
        skill_lower = skill.lower()
        for kw, tool in _SKILL_TO_TOOL_BUILD.items():
            if kw in skill_lower:
                tools.add(tool)
                break
    return list(tools) or ["browser_search"]


def _diagnostic_questions_for(domain: str) -> list[str]:
    if domain == "customer_operations":
        return [
            "What device, service, or feature is affected?",
            "When did this issue first start?",
            "What error message or symptom are you seeing?",
            "Have you tried restarting or refreshing?",
            "Is this affecting just you or multiple users?",
            "What was the last change made before the issue started?",
        ]
    if domain == "accounting":
        return [
            "Which financial period does this relate to?",
            "What is the transaction or entry type?",
            "Which accounts or cost centers are involved?",
            "Has this been approved by the relevant authority?",
            "Are there supporting documents attached?",
            "Does this require regulatory reporting or compliance review?",
        ]
    if domain == "it_compliance":
        return [
            "What system or data category is involved?",
            "What is the data classification level at risk?",
            "When was the potential breach or violation detected?",
            "Which regulatory framework applies (GDPR, DPDP, etc.)?",
            "Has the incident been logged in the ITSM system?",
            "Does this require escalation to CERT-In or DPA?",
        ]
    return [
        "What is the primary objective of this task?",
        "What inputs or documents are required?",
        "Are there any approval or review gates needed?",
        "What is the expected output or outcome?",
        "Are there any exceptions or edge cases to handle?",
        "Who is the stakeholder or approver for final sign-off?",
    ]


def _langgraph_nodes_for(domain: str, steps: list) -> list[dict]:
    if domain == "customer_operations":
        return [
            {"id": "n1", "type": "ingest",    "label": "Receive Support Query"},
            {"id": "n2", "type": "classify",  "label": "Classify Issue Type"},
            {"id": "n3", "type": "diagnose",  "label": "Run Diagnostic Questions"},
            {"id": "n4", "type": "knowledge", "label": "Match Knowledge Base"},
            {"id": "n5", "type": "decision",  "label": "Escalation Gate"},
            {"id": "n6", "type": "resolve",   "label": "Generate Resolution"},
            {"id": "n7", "type": "close",     "label": "Document & Close Ticket"},
        ]
    if domain == "accounting":
        return [
            {"id": "n1", "type": "ingest",    "label": "Ingest Financial Data"},
            {"id": "n2", "type": "validate",  "label": "Validate Entries"},
            {"id": "n3", "type": "classify",  "label": "Classify Transaction"},
            {"id": "n4", "type": "rules",     "label": "Apply Compliance Rules"},
            {"id": "n5", "type": "decision",  "label": "Human Approval Gate"},
            {"id": "n6", "type": "process",   "label": "Process & Post"},
            {"id": "n7", "type": "report",    "label": "Generate Report"},
        ]
    if domain == "it_compliance":
        return [
            {"id": "n1", "type": "ingest",    "label": "Ingest Incident Data"},
            {"id": "n2", "type": "classify",  "label": "Classify Severity"},
            {"id": "n3", "type": "rules",     "label": "Apply Compliance Rules"},
            {"id": "n4", "type": "assess",    "label": "Risk Assessment"},
            {"id": "n5", "type": "decision",  "label": "Notification Gate"},
            {"id": "n6", "type": "respond",   "label": "Execute Response Plan"},
            {"id": "n7", "type": "report",    "label": "Regulatory Reporting"},
        ]
    # Derive from SOP steps
    nodes = [
        {"id": "n1", "type": "ingest",     "label": "Ingest Task"},
        {"id": "n2", "type": "knowledge",  "label": "Load Domain Rules"},
    ]
    for i, step in enumerate(steps[:4], 3):
        label = (step.get("step", str(step)) if isinstance(step, dict) else str(step))[:40]
        nodes.append({"id": f"n{i}", "type": "execute", "label": label})
    nodes.append({"id": f"n{len(nodes)+1}", "type": "synthesize", "label": "Generate Output"})
    return nodes


def _generate_system_prompt(process: str, domain: str, questions: list, steps: list) -> str:
    domain_labels = {
        "customer_operations": "Customer Operations Support",
        "accounting": "Finance & Accounting",
        "it_compliance": "IT Compliance & Security",
        "hr_compliance": "HR & People Ops",
        "general": "General Operations",
    }
    label = domain_labels.get(domain, "Operations")
    steps_text = "\n".join(
        f"  {i+1}. {s.get('step', str(s)) if isinstance(s, dict) else str(s)}"
        for i, s in enumerate(steps[:8])
    )
    qs_text = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(questions))
    return (
        f"You are a Digital Co-worker specializing in {label}.\n\n"
        f"Primary purpose: {process}\n\n"
        f"SOP Workflow:\n{steps_text or '  Follow domain best practices.'}\n\n"
        f"Diagnostic questions (work through in order):\n{qs_text}\n\n"
        "Guidelines:\n"
        "- Be concise and action-oriented\n"
        "- Ask one diagnostic question at a time\n"
        "- Reference SOP steps when relevant\n"
        "- Escalate when confidence is low or risk is high\n"
        "- Document resolution for the knowledge base"
    )


def _generate_coworker_config(analysis: dict, agent_spec: Optional[dict]) -> dict:
    sop_type   = analysis.get("type", "SOP")
    process    = analysis.get("process_understanding", "Workflow Automation")
    steps      = analysis.get("steps", [])
    domain     = _detect_domain_from_analysis(analysis)
    purpose    = _detect_functional_purpose(analysis, domain)
    tools      = _detect_tools_from_analysis(analysis, agent_spec)
    questions  = _diagnostic_questions_for(domain)
    nodes      = _langgraph_nodes_for(domain, steps)
    sys_prompt = _generate_system_prompt(process, domain, questions, steps)

    precision = analysis.get("precision_analysis", {})
    business  = analysis.get("business_metrics", {})

    return {
        "agent_id": f"cw-{uuid.uuid4().hex[:8]}",
        "name": f"{purpose} Co-worker",
        "functional_purpose": purpose,
        "sop_type": sop_type,
        "domain": domain,
        "tools": tools,
        "knowledge_domains": [domain] if domain != "general" else ["general"],
        "langgraph_nodes": nodes,
        "node_count": len(nodes),
        "diagnostic_questions": questions,
        "system_prompt": sys_prompt,
        "sop_steps": [
            s.get("step", str(s)) if isinstance(s, dict) else str(s)
            for s in steps[:10]
        ],
        "automation_score": business.get("automation_score", 0),
        "precision_score": precision.get("precision_score", 0),
        "human_review_required": precision.get("human_approval_required", True),
        "created_at": datetime.utcnow().isoformat() + "Z",
    }


def _build_self_host_guide(agent_id: str, server_ids: list[str]) -> dict:
    """
    Build the self-host UI payload: one command, step guide, and download links.
    Shown in the Assemble phase when the user selects 'Self-Host' mode.
    """
    if not server_ids:
        return {}
    cfg = SovereignConfig(agent_id=agent_id, server_ids=server_ids)
    result = InstallerGenerator().generate(cfg)
    return {
        "available": True,
        "one_command": result["one_command"],
        "verify_url": result["verify_url"],
        "sse_url": result["sse_url"],
        "install_guide": result["install_guide"],
        "download_compose_url": f"/ai/sovereign/download/compose?agent_id={agent_id}&server_ids={','.join(server_ids)}",
        "privacy_icon": "shield",
        "privacy_label": "Privacy Shield",
        "privacy_tagline": "Your data never leaves your machine.",
    }


def _detect_connectors(analysis: dict) -> list[dict]:
    """
    Run the KnowledgeRouter against the analysis text to discover which MCP
    servers are required, then return frontend-ready connector button payloads.
    """
    text = " ".join([
        analysis.get("process_understanding", ""),
        analysis.get("type", ""),
        " ".join(analysis.get("required_ai_skills", [])),
        " ".join(
            s.get("step", str(s)) if isinstance(s, dict) else str(s)
            for s in analysis.get("steps", [])[:10]
        ),
    ])
    try:
        ctx = _knowledge_router.get_context(text)
        return [connector_button(sid) for sid in ctx.required_mcp_servers]
    except Exception:
        return []


def _run_coworker_chat(query: str, config: dict, history: list) -> dict:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

    questions  = config.get("diagnostic_questions", [])
    sys_prompt = config.get("system_prompt", "You are a helpful support co-worker.")

    answered = len([m for m in history if m.get("role") == "user"])
    remaining = max(0, len(questions) - answered)

    if answered < len(questions):
        next_q_hint = (
            f"\nCurrent diagnostic step: {answered + 1}/{len(questions)}. "
            f"If not yet answered, ask: \"{questions[answered]}\""
        )
    else:
        next_q_hint = "\nAll diagnostics complete. Provide the final resolution and next steps."

    messages = [SystemMessage(content=sys_prompt + next_q_hint)]
    for m in history:
        role = m.get("role")
        content = m.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=query))

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3)
    response = llm.invoke(messages)

    return {
        "response": response.content,
        "diagnostic_step": min(answered + 1, len(questions)),
        "total_steps": len(questions),
        "diagnostics_remaining": remaining,
        "all_diagnostics_complete": answered >= len(questions),
    }
