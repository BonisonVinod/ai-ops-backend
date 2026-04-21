"""
agent_spec_service.py

Two outputs from a single SOP analysis:
1. agent_spec  — static workflow graph (existing format, unchanged)
2. factory_run_spec — dynamic spec the Agentic Factory Composer can consume directly
"""

import json


# ---------------------------------------------------------------------------
# Tool + domain detection helpers
# ---------------------------------------------------------------------------

_SKILL_TO_TOOL = {
    "pdf": "extract_document",
    "docx": "extract_document",
    "document": "extract_document",
    "csv": "read_csv_as_json",
    "spreadsheet": "read_csv_as_json",
    "excel": "read_csv_as_json",
    "python": "execute_python",
    "pandas": "execute_python",
    "calculation": "execute_python",
    "data processing": "execute_python",
    "code": "generate_code",
    "script": "generate_code",
    "web": "browser_search",
    "search": "browser_search",
    "api": "browser_search",
    "real-time": "browser_search",
}

_DOMAIN_KEYWORDS = {
    "accounting": {
        "payroll", "salary", "tds", "gst", "invoice", "tax", "audit",
        "balance sheet", "ledger", "journal", "financial", "pf", "provident fund",
        "accounts payable", "accounts receivable", "depreciation", "budget",
    },
    "it_compliance": {
        "data privacy", "pii", "gdpr", "dpdp", "security", "iso 27001",
        "access control", "breach", "incident", "cert-in", "sebi",
        "penetration test", "vapt",
    },
    "hr_compliance": {
        "recruitment", "onboarding", "performance", "termination", "leave",
        "posh", "disciplinary", "kpi", "appraisal", "hiring",
    },
}


def _detect_tools(insights: dict) -> list[str]:
    skills = insights.get("required_ai_skills", [])
    tools = set()
    for skill in skills:
        skill_lower = skill.lower()
        for keyword, tool in _SKILL_TO_TOOL.items():
            if keyword in skill_lower:
                tools.add(tool)
                break
    # Sensible default
    if not tools:
        tools.add("browser_search")
    return list(tools)


def _detect_domain(insights: dict) -> str:
    process = (insights.get("process_understanding", "") + " " +
               " ".join(insights.get("required_ai_skills", []))).lower()

    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if any(kw in process for kw in keywords):
            return domain
    return "general"


def _map_plan_to_complexity(plan: str) -> str:
    return {"Standard": "low", "Pro": "medium", "Enterprise": "high"}.get(plan, "medium")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_agent_spec(insights: dict) -> dict:
    """
    Returns:
      {
        "goal": str,
        "inputs": [...],
        "workflow": [...],          # static step graph (original format)
        "outputs": [...],
        "factory_run_spec": {...}   # NEW: dynamic spec for the Agentic Factory
      }
    """
    if isinstance(insights, str):
        insights = json.loads(insights)

    steps = insights.get("steps", [])

    # -----------------------------------------------------------------------
    # Static workflow graph (original logic — unchanged)
    # -----------------------------------------------------------------------
    workflow = []
    previous_output = "input_data"

    for i, step in enumerate(steps):
        step_text = step.get("step", "") if isinstance(step, dict) else str(step)
        step_name = step_text.lower()

        is_decision = any(kw in step_name for kw in [" if ", " if(", " whether ", " else ", " based on "])

        if is_decision:
            step_type = "decision"
        elif any(w in step_name for w in ["validate", "verify", "check format"]):
            step_type = "validate"
        elif any(w in step_name for w in ["send", "call", "trigger", "notify"]):
            step_type = "api_call"
        elif any(w in step_name for w in ["store", "persist", "save", "update", "write"]):
            step_type = "database"
        elif any(w in step_name for w in ["generate", "create", "render"]):
            step_type = "generate"
        else:
            step_type = "transform"

        output_name = f"step_{i+1}_output"
        step_data = {
            "id": f"step_{i+1}",
            "name": step_text,
            "type": step_type,
            "input": [previous_output],
            "output": [output_name],
            "condition": None,
        }

        if step_type == "decision":
            step_data["condition"] = {
                "key": f"step_{i+1}_decision",
                "label": step_text,
                "operator": "check",
                "value": True,
            }
            step_data["true_next"]  = f"step_{i+2}" if i + 1 < len(steps) else None
            step_data["false_next"] = f"step_{i+1}_fallback"
            fallback = {
                "id": f"step_{i+1}_fallback",
                "name": "Request missing or invalid input from user",
                "type": "user_input",
                "input": [previous_output],
                "output": [f"step_{i+1}_fallback_output"],
                "condition": None,
            }
            workflow.append(step_data)
            workflow.append(fallback)
        else:
            workflow.append(step_data)

        previous_output = output_name

    # -----------------------------------------------------------------------
    # Factory RunSpec (NEW)
    # -----------------------------------------------------------------------
    precision = insights.get("precision_analysis", {})
    technical = insights.get("technical_feasibility", {})
    business  = insights.get("business_metrics", {})

    recommended_tools = _detect_tools(insights)
    domain            = _detect_domain(insights)
    complexity        = _map_plan_to_complexity(business.get("recommended_plan", "Pro"))

    error_sensitivity = precision.get("error_sensitivity", "Medium")
    human_required    = precision.get("human_approval_required", True)
    precision_score   = precision.get("precision_score", 50)

    factory_run_spec = {
        "domain": domain,
        "recommended_tools": recommended_tools,
        "complexity": complexity,
        "human_review_required": human_required,
        "precision_score": precision_score,
        "error_sensitivity": error_sensitivity,
        "suggested_knowledge_domains": [domain] if domain != "general" else [],
        "automation_score": business.get("automation_score", technical.get("score", 50)),
        "recommended_plan": business.get("recommended_plan", "Pro"),
        "setup_fee": business.get("setup_fee", "N/A"),
        "running_cost": business.get("running_cost", "N/A"),
        "primary_tools_from_analysis": technical.get("primary_tools", []),
        "factory_task_hint": (
            f"Execute {insights.get('type', 'SOP')}: {insights.get('process_understanding', '')[:200]}"
        ),
        "blocked_actions": _get_blocked_actions(human_required, precision_score),
    }

    return {
        "goal": insights.get("process_understanding", ""),
        "inputs": ["input_data"],
        "workflow": workflow,
        "outputs": [previous_output],
        "factory_run_spec": factory_run_spec,
    }


def _get_blocked_actions(human_required: bool, precision_score: int) -> list[str]:
    base = ["approve_payment", "send_external_communication"]
    if human_required or precision_score >= 75:
        base += ["post_journal_entry", "file_regulatory_return", "remit_tax", "terminate_employee"]
    if precision_score >= 90:
        base += ["modify_database_schema", "deploy_to_production", "delete_records"]
    return base
