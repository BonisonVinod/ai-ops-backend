"""
AccountingAuditAgent — Prototype Agent built by the Agentic Factory.

This is a fully wired, end-to-end prototype that demonstrates the Factory pattern:
  1. READ   — ingests a CSV ledger/transaction file
  2. CONSULT — loads accounting_rules.json via KnowledgeRouter
  3. ANALYZE — runs compliance checks against IndAS, TDS, GST, PF rules
  4. PROPOSE — generates a change proposal (journal entry corrections, flag list)
  5. PAUSE   — human-interrupt before any proposed changes are finalized
  6. REPORT  — synthesizes final audit memo

This agent is wired directly to the Agentic Factory Composer (LangGraph StateMachine)
and uses SqliteSaver for thread persistence so audits can be paused and resumed.
"""

import json
import uuid
from pathlib import Path
from typing import Optional, TypedDict, Annotated
from operator import add

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.sqlite import SqliteSaver

from app.engine.tools.document_tool import read_csv_as_json
from app.engine.knowledge.knowledge_router import KnowledgeRouter


# ---------------------------------------------------------------------------
# Agent-specific state
# ---------------------------------------------------------------------------

class AuditState(TypedDict):
    # Inputs
    csv_file_path: str
    audit_period: str
    thread_id: str

    # Data
    raw_ledger: Optional[str]
    ledger_rows: Optional[list]
    knowledge_context: Optional[dict]

    # Analysis
    anomalies: list[str]
    tds_flags: list[str]
    gst_flags: list[str]
    pf_flags: list[str]
    other_flags: list[str]

    # Proposal
    proposed_changes: list[dict]
    change_summary: str

    # Human gate
    human_feedback: Optional[str]
    human_approved: bool

    # Output
    audit_memo: Optional[str]
    messages: Annotated[list[BaseMessage], add]
    error: Optional[str]


# ---------------------------------------------------------------------------
# LLM + prompts
# ---------------------------------------------------------------------------

_ANALYZE_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a Chartered Accountant AI auditing an Indian company's ledger/transactions. "
        "Apply these mandatory rules strictly:\n\n"
        "{knowledge_rules}\n\n"
        "Analyze the provided ledger data and identify:\n"
        "1. TDS violations (194C contractor > ₹30k without TDS, 194J professional > ₹30k without TDS)\n"
        "2. GST ITC mismatches (supplier charges GST but no ITC recorded)\n"
        "3. PF non-compliance (employees with Basic > ₹15,000 without PF deduction)\n"
        "4. Expense materiality (single line items > 5% of total revenue)\n"
        "5. Any other IndAS/Companies Act flags\n\n"
        "Return JSON with keys: tds_flags, gst_flags, pf_flags, other_flags, anomalies\n"
        "Each is a list of strings. Be specific: include amounts, party names, rule IDs.",
    ),
    ("human", "Audit period: {audit_period}\n\nLedger data (JSON):\n{ledger_data}"),
])

_PROPOSE_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a CA drafting audit adjustment proposals. "
        "For each flag identified, propose a specific corrective action. "
        "Return JSON with: proposed_changes (list of objects with: flag, action, journal_entry, "
        "amount_inr, risk_level, requires_human_approval), change_summary (string).",
    ),
    (
        "human",
        "Audit flags:\n{flags}\n\nLedger context:\n{ledger_summary}\n\n"
        "Propose corrective journal entries and actions.",
    ),
])

_MEMO_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a senior CA preparing a formal audit memo. "
        "Structure: Executive Summary, Findings (by risk level), "
        "Proposed Adjustments (approved/rejected by reviewer), "
        "Next Steps, Compliance Sign-off Requirements.",
    ),
    (
        "human",
        "Audit Period: {audit_period}\nFile: {csv_path}\n\n"
        "Findings:\n{flags}\n\n"
        "Proposed Changes:\n{proposals}\n\n"
        "Human Reviewer Feedback: {human_feedback}\n\n"
        "Draft the formal audit memo.",
    ),
])


def _get_llm():
    return ChatOpenAI(model="gpt-4o-mini", temperature=0.1)


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

def read_ledger(state: AuditState) -> dict:
    """Step 1: Read the CSV ledger file."""
    csv_path = state["csv_file_path"]
    result = read_csv_as_json.invoke(csv_path)

    # Try to parse JSON rows for structured analysis
    rows = []
    try:
        rows = json.loads(result)
    except Exception:
        pass

    return {
        "raw_ledger": result[:8000],
        "ledger_rows": rows[:200] if rows else [],
        "messages": [HumanMessage(content=f"[Ledger read] {csv_path} — {len(rows)} rows")],
    }


def consult_knowledge(state: AuditState) -> dict:
    """Step 2: Load accounting rules from KnowledgeRouter."""
    kr = KnowledgeRouter()
    task_desc = f"Accounting audit for period {state['audit_period']} — ledger CSV analysis"
    ctx = kr.get_context(task_desc, planned_actions=["execute_python"])
    ctx_dict = ctx.to_dict()

    return {
        "knowledge_context": ctx_dict,
        "messages": [AIMessage(content=f"[Knowledge loaded] {len(ctx.applicable_rules)} accounting rules active")],
    }


def analyze_ledger(state: AuditState) -> dict:
    """Step 3: Analyze ledger data against accounting rules."""
    ctx = state.get("knowledge_context", {})
    rules_text = ctx.get("system_prompt_injection", "Apply standard IndAS and Indian tax rules.")[:3000]
    ledger_data = state.get("raw_ledger", "No data")[:5000]

    try:
        llm = _get_llm()
        chain = _ANALYZE_PROMPT | llm
        response = chain.invoke({
            "knowledge_rules": rules_text,
            "audit_period": state["audit_period"],
            "ledger_data": ledger_data,
        })

        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]

        analysis = json.loads(content)
    except Exception as e:
        analysis = {
            "tds_flags": [f"Analysis error: {str(e)}"],
            "gst_flags": [],
            "pf_flags": [],
            "other_flags": [],
            "anomalies": [],
        }

    return {
        "tds_flags": analysis.get("tds_flags", []),
        "gst_flags": analysis.get("gst_flags", []),
        "pf_flags": analysis.get("pf_flags", []),
        "other_flags": analysis.get("other_flags", []),
        "anomalies": analysis.get("anomalies", []),
        "messages": [AIMessage(content=(
            f"[Analysis complete] TDS: {len(analysis.get('tds_flags',[]))}, "
            f"GST: {len(analysis.get('gst_flags',[]))}, "
            f"PF: {len(analysis.get('pf_flags',[]))}, "
            f"Other: {len(analysis.get('other_flags',[]))}"
        ))],
    }


def propose_changes(state: AuditState) -> dict:
    """Step 4: Generate corrective journal entry proposals for each flag."""
    all_flags = (
        state.get("tds_flags", []) +
        state.get("gst_flags", []) +
        state.get("pf_flags", []) +
        state.get("other_flags", []) +
        state.get("anomalies", [])
    )

    if not all_flags:
        return {
            "proposed_changes": [],
            "change_summary": "No flags identified. Ledger appears compliant.",
            "messages": [AIMessage(content="[No flags] Ledger is clean.")],
        }

    ledger_rows = state.get("ledger_rows", [])
    ledger_summary = json.dumps(ledger_rows[:10], indent=2) if ledger_rows else "No structured data"

    try:
        llm = _get_llm()
        chain = _PROPOSE_PROMPT | llm
        response = chain.invoke({
            "flags": "\n".join(f"- {f}" for f in all_flags),
            "ledger_summary": ledger_summary[:2000],
        })

        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]

        proposal = json.loads(content)
    except Exception as e:
        proposal = {
            "proposed_changes": [{"flag": f, "action": "Manual review required", "risk_level": "high", "requires_human_approval": True} for f in all_flags[:5]],
            "change_summary": f"Proposals generated with errors: {str(e)}",
        }

    return {
        "proposed_changes": proposal.get("proposed_changes", []),
        "change_summary": proposal.get("change_summary", ""),
        "messages": [AIMessage(content=f"[Proposals] {len(proposal.get('proposed_changes', []))} changes proposed")],
    }


def human_approval_gate(state: AuditState) -> dict:
    """
    Step 5: Human-interrupt gate.

    This node is paired with interrupt_before=["human_approval_gate"] in the compiled graph.
    The graph PAUSES before this node runs on first pass. When the caller resumes (via
    agent.resume(thread_id, feedback)), the state is updated with human_feedback and this
    node executes — reading the feedback directly from state instead of calling interrupt().
    """
    feedback_str = state.get("human_feedback") or "pending"

    approved = feedback_str.lower().startswith(("approved", "partial"))

    return {
        "human_feedback": feedback_str,
        "human_approved": approved,
        "messages": [HumanMessage(content=f"[CA Review] {feedback_str[:200]}")],
    }


def generate_memo(state: AuditState) -> dict:
    """Step 6: Generate the final formal audit memo."""
    all_flags = (
        state.get("tds_flags", []) +
        state.get("gst_flags", []) +
        state.get("pf_flags", []) +
        state.get("other_flags", []) +
        state.get("anomalies", [])
    )
    flags_text = "\n".join(f"- {f}" for f in all_flags) if all_flags else "None identified."

    proposals_text = json.dumps(state.get("proposed_changes", []), indent=2)[:3000]
    human_feedback = state.get("human_feedback", "No reviewer feedback recorded.")

    try:
        llm = _get_llm()
        chain = _MEMO_PROMPT | llm
        response = chain.invoke({
            "audit_period": state["audit_period"],
            "csv_path": state["csv_file_path"],
            "flags": flags_text,
            "proposals": proposals_text,
            "human_feedback": human_feedback,
        })
        memo = response.content
    except Exception as e:
        memo = (
            f"AUDIT MEMO — {state['audit_period']}\n\n"
            f"File: {state['csv_file_path']}\n\n"
            f"Findings:\n{flags_text}\n\n"
            f"Proposals:\n{proposals_text}\n\n"
            f"Human Feedback: {human_feedback}\n\n"
            f"[Memo generation error: {str(e)}]"
        )

    return {
        "audit_memo": memo,
        "messages": [AIMessage(content=f"[Audit memo ready] {len(memo)} chars")],
    }


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def _build_audit_graph() -> StateGraph:
    builder = StateGraph(AuditState)

    builder.add_node("read_ledger", read_ledger)
    builder.add_node("consult_knowledge", consult_knowledge)
    builder.add_node("analyze_ledger", analyze_ledger)
    builder.add_node("propose_changes", propose_changes)
    builder.add_node("human_approval_gate", human_approval_gate)
    builder.add_node("generate_memo", generate_memo)

    builder.add_edge(START, "read_ledger")
    builder.add_edge("read_ledger", "consult_knowledge")
    builder.add_edge("consult_knowledge", "analyze_ledger")
    builder.add_edge("analyze_ledger", "propose_changes")
    builder.add_edge("propose_changes", "human_approval_gate")
    builder.add_edge("human_approval_gate", "generate_memo")
    builder.add_edge("generate_memo", END)

    return builder


class AccountingAuditAgent:
    """
    Prototype agent for accounting audit tasks.
    Orchestrates: Read CSV → Consult Rules → Analyze → Propose → Human Gate → Memo.

    Usage:
        agent = AccountingAuditAgent()
        result = agent.run("path/to/ledger.csv", "Q4 FY2025-26")
        # If interrupted for human review:
        result = agent.resume(thread_id, "approved: all figures verified")
    """

    def __init__(self, db_path: str = "audit_checkpoints.db"):
        self.db_path = db_path

    def run(
        self,
        csv_file_path: str,
        audit_period: str = "FY 2025-26",
        thread_id: Optional[str] = None,
    ) -> dict:
        if thread_id is None:
            thread_id = f"audit-{uuid.uuid4().hex[:8]}"

        initial_state = {
            "csv_file_path": csv_file_path,
            "audit_period": audit_period,
            "thread_id": thread_id,
            "raw_ledger": None,
            "ledger_rows": None,
            "knowledge_context": None,
            "anomalies": [],
            "tds_flags": [],
            "gst_flags": [],
            "pf_flags": [],
            "other_flags": [],
            "proposed_changes": [],
            "change_summary": "",
            "human_feedback": None,
            "human_approved": False,
            "audit_memo": None,
            "messages": [],
            "error": None,
        }

        builder = _build_audit_graph()
        config = {"configurable": {"thread_id": thread_id}}

        with SqliteSaver.from_conn_string(self.db_path) as checkpointer:
            graph = builder.compile(
                checkpointer=checkpointer,
                interrupt_before=["human_approval_gate"],
            )
            result = graph.invoke(initial_state, config)

        result["thread_id"] = thread_id
        return result

    def resume(self, thread_id: str, human_feedback: str) -> dict:
        """Resume an interrupted audit thread after human CA review."""
        builder = _build_audit_graph()
        config = {"configurable": {"thread_id": thread_id}}

        with SqliteSaver.from_conn_string(self.db_path) as checkpointer:
            graph = builder.compile(
                checkpointer=checkpointer,
                interrupt_before=["human_approval_gate"],
            )
            graph.update_state(config, {"human_feedback": human_feedback})
            result = graph.invoke(None, config)

        result["thread_id"] = thread_id
        return result
