"""
KnowledgeRouter — injects domain-specific rules into agent context.

Given an SOP type or free-text description, the router:
1. Detects the relevant domain(s) via keyword + LLM classification
2. Loads the matching JSON rule file(s) from knowledge/rules/
3. Filters to only the rules applicable to the agent's planned actions
4. Returns a structured KnowledgeContext the composer injects into the agent's system prompt
"""

import json
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field as PydanticField


# ---------------------------------------------------------------------------
# Rule file registry
# ---------------------------------------------------------------------------

RULES_DIR = Path(__file__).parent / "rules"

DOMAIN_REGISTRY = {
    "accounting": RULES_DIR / "accounting_rules.json",
    "it_compliance": RULES_DIR / "it_compliance.json",
}

DOMAIN_KEYWORDS = {
    "accounting": {
        "payroll", "salary", "tds", "gst", "invoice", "tax", "audit", "balance sheet",
        "profit", "loss", "expense", "revenue", "ledger", "journal", "voucher",
        "accounts payable", "accounts receivable", "depreciation", "budget",
        "financial", "tally", "zoho books", "itc", "reconciliation", "indas",
        "pf", "provident fund", "esic", "esi", "cash flow",
    },
    "it_compliance": {
        "data privacy", "pii", "gdpr", "dpdp", "personal data", "cyber", "security",
        "iso 27001", "vapt", "penetration test", "access control", "encryption",
        "breach", "incident", "cert-in", "sebi cscrf", "rbi itgf", "log retention",
        "aadhaar", "pan", "biometric", "sensitive data", "data classification",
    },
    "customer_operations": {
        "troubleshooting", "troubleshoot", "sop", "escalation", "escalate",
        "diagnostic", "diagnose", "support", "helpdesk", "help desk", "ticket",
        "customer complaint", "resolution", "triage", "runbook", "playbook",
        "incident response", "service request", "call script", "agent guide",
    },
}

# ---------------------------------------------------------------------------
# Accounting-exclusive keywords — presence of ANY of these MUST block
# customer_operations domain classification regardless of other signals.
# ---------------------------------------------------------------------------

ACCOUNTING_EXCLUSIVE_KEYWORDS: set[str] = {
    "accountant", "accountants", "tds", "gst", "ledger", "ledgers",
    "itc", "gstr", "tally", "zoho books", "balance sheet", "journal entry",
    "accounts payable", "accounts receivable", "bookkeeping", "invoice matching",
    "tax deducted at source", "input tax credit", "gst reconciliation",
}

# Domains that are suppressed when accounting-exclusive keywords are detected
_ACCOUNTING_EXCLUSIVE_BLOCKS: set[str] = {"customer_operations"}

# ---------------------------------------------------------------------------
# MCP server detection keywords
# ---------------------------------------------------------------------------

MCP_SERVER_KEYWORDS: dict[str, set[str]] = {
    "gmail": {
        "email", "e-mail", "send mail", "send email", "inbox", "outbox",
        "customer contact", "contact customer", "notify customer", "mail customer",
        "follow up", "follow-up", "reply to customer", "email notification",
        "correspondence", "customer communication", "notify via email",
    },
    "google_sheets": {
        "spreadsheet", "google sheets", "data tracking", "track data",
        "data entry", "record keeping", "ledger", "tracker", "log entries",
        "data ledger", "update sheet", "append row", "tracking sheet",
        "report sheet", "data table", "fill spreadsheet", "data log",
    },
    "slack": {
        "slack", "slack message", "send slack", "slack notification",
        "team notification", "channel alert", "post to channel",
        "notify team", "alert team", "team message",
    },
}


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

@dataclass
class ApplicableRule:
    id: str
    name: str
    agent_rule: str
    risk_level: str
    human_approval_required: bool


@dataclass
class KnowledgeContext:
    domains: list[str]
    applicable_rules: list[ApplicableRule]
    blocked_actions: list[str]
    auto_approvable_actions: list[str]
    variance_thresholds: dict
    system_prompt_injection: str
    human_review_required: bool = False
    required_mcp_servers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "domains": self.domains,
            "applicable_rules": [
                {
                    "id": r.id,
                    "name": r.name,
                    "agent_rule": r.agent_rule,
                    "risk_level": r.risk_level,
                    "human_approval_required": r.human_approval_required,
                }
                for r in self.applicable_rules
            ],
            "blocked_actions": self.blocked_actions,
            "auto_approvable_actions": self.auto_approvable_actions,
            "variance_thresholds": self.variance_thresholds,
            "human_review_required": self.human_review_required,
            "system_prompt_injection": self.system_prompt_injection,
            "required_mcp_servers": self.required_mcp_servers,
        }


# ---------------------------------------------------------------------------
# Domain classification (LLM-backed)
# ---------------------------------------------------------------------------

class DomainClassification(BaseModel):
    domains: list[str] = PydanticField(
        description="List of applicable domains from: accounting, it_compliance, customer_operations, hr_compliance, general"
    )
    confidence: float = PydanticField(description="0.0 to 1.0")
    reasoning: str = PydanticField(description="Brief explanation of domain selection")


_CLASSIFY_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "Classify the given SOP or task description into one or more knowledge domains. "
        "Available domains: accounting, it_compliance, customer_operations, hr_compliance, general. "
        "CRITICAL RULE: If the text contains any of the following terms — accountant, TDS, GST, "
        "ledger, ITC, GSTR, balance sheet, accounts payable, accounts receivable — you MUST classify "
        "as 'accounting' and MUST NOT include 'customer_operations'. "
        "Use 'customer_operations' ONLY for troubleshooting guides, support SOPs, escalation procedures, "
        "diagnostic runbooks, or helpdesk workflows that contain NO accounting/finance terminology. "
        "Return JSON with: domains (list), confidence (float), reasoning (string).",
    ),
    ("human", "Task/SOP description:\n{text}"),
])


# ---------------------------------------------------------------------------
# KnowledgeRouter
# ---------------------------------------------------------------------------

class KnowledgeRouter:
    """
    Routes any SOP/task through the domain knowledge base and returns a
    KnowledgeContext ready to be injected into an agent's system prompt.
    """

    def __init__(self, model: str = "gpt-4o-mini", fallback_to_keywords: bool = True):
        self.llm = ChatOpenAI(model=model, temperature=0.0)
        self.parser = JsonOutputParser(pydantic_object=DomainClassification)
        self.classify_chain = _CLASSIFY_PROMPT | self.llm | self.parser
        self.fallback_to_keywords = fallback_to_keywords
        self._rule_cache: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_context(self, text: str, planned_actions: Optional[list[str]] = None) -> KnowledgeContext:
        """
        Main entry point. Given a task description and (optionally) the
        list of actions the agent plans to take, return a KnowledgeContext.
        """
        domains = self._classify_domains(text)
        all_rules: list[ApplicableRule] = []
        all_blocked: list[str] = []
        all_auto: list[str] = []
        all_thresholds: dict = {}

        for domain in domains:
            rule_data = self._load_rules(domain)
            if not rule_data:
                continue

            rules = self._filter_rules(rule_data.get("standards", []), planned_actions)
            all_rules.extend(rules)
            all_blocked.extend(rule_data.get("blocked_auto_actions", []))
            all_auto.extend(rule_data.get("auto_approvable_actions", []))
            all_thresholds.update(rule_data.get("variance_thresholds", {}))

        human_required = any(r.human_approval_required for r in all_rules)
        if planned_actions:
            human_required = human_required or any(a in all_blocked for a in planned_actions)

        prompt_injection = self._build_system_injection(domains, all_rules, all_blocked)
        required_mcp = self._detect_mcp_servers(text)

        return KnowledgeContext(
            domains=domains,
            applicable_rules=all_rules,
            blocked_actions=list(set(all_blocked)),
            auto_approvable_actions=list(set(all_auto)),
            variance_thresholds=all_thresholds,
            system_prompt_injection=prompt_injection,
            human_review_required=human_required,
            required_mcp_servers=required_mcp,
        )

    def get_context_dict(self, text: str, planned_actions: Optional[list[str]] = None) -> dict:
        return self.get_context(text, planned_actions).to_dict()

    # ------------------------------------------------------------------
    # Domain classification
    # ------------------------------------------------------------------

    def _classify_domains(self, text: str) -> list[str]:
        text_lower = text.lower()

        # Exclusive accounting check — MUST block competing domains if triggered
        accounting_exclusive_hit = any(kw in text_lower for kw in ACCOUNTING_EXCLUSIVE_KEYWORDS)

        keyword_domains = self._keyword_classify(text)

        # Strip blocked domains from keyword results immediately
        if accounting_exclusive_hit:
            keyword_domains = [d for d in keyword_domains if d not in _ACCOUNTING_EXCLUSIVE_BLOCKS]
            if "accounting" not in keyword_domains:
                keyword_domains.append("accounting")

        try:
            result = self.classify_chain.invoke({"text": text})
            llm_domains = result.get("domains", []) if isinstance(result, dict) else []

            # LLM verification: honour exclusive block regardless of LLM output
            if accounting_exclusive_hit:
                llm_domains = [d for d in llm_domains if d not in _ACCOUNTING_EXCLUSIVE_BLOCKS]

            _known = set(DOMAIN_REGISTRY) | {"accounting", "it_compliance", "hr_compliance",
                                              "customer_operations", "general"}
            merged = list(set(keyword_domains + [d for d in llm_domains if d in _known]))

            # Final guard — exclusive block cannot be undone
            if accounting_exclusive_hit:
                merged = [d for d in merged if d not in _ACCOUNTING_EXCLUSIVE_BLOCKS]

            return merged if merged else ["general"]
        except Exception:
            if self.fallback_to_keywords:
                return keyword_domains if keyword_domains else ["general"]
            return ["general"]

    def _keyword_classify(self, text: str) -> list[str]:
        text_lower = text.lower()
        matched = []
        for domain, keywords in DOMAIN_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                matched.append(domain)
        return matched

    def _detect_mcp_servers(self, text: str) -> list[str]:
        """Scan text for signals that indicate which MCP servers are needed."""
        text_lower = text.lower()
        detected = []
        for server_id, keywords in MCP_SERVER_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                detected.append(server_id)
        return detected

    # ------------------------------------------------------------------
    # Rule loading & filtering
    # ------------------------------------------------------------------

    def _load_rules(self, domain: str) -> dict:
        if domain in self._rule_cache:
            return self._rule_cache[domain]

        rule_path = DOMAIN_REGISTRY.get(domain)
        if not rule_path or not rule_path.exists():
            return {}

        with open(rule_path, "r") as f:
            data = json.load(f)
        self._rule_cache[domain] = data
        return data

    def _filter_rules(
        self,
        standards: list[dict],
        planned_actions: Optional[list[str]],
    ) -> list[ApplicableRule]:
        rules = []
        for s in standards:
            rules.append(ApplicableRule(
                id=s["id"],
                name=s["name"],
                agent_rule=s["agent_rule"],
                risk_level=s["risk_level"],
                human_approval_required=s.get("human_approval_required", False),
            ))
        return rules

    # ------------------------------------------------------------------
    # System prompt injection builder
    # ------------------------------------------------------------------

    # Friendly display names for domains shown to users
    _DOMAIN_LABELS = {
        "accounting": "Finance & Accounting",
        "it_compliance": "IT Compliance & Security",
        "customer_operations": "Customer Operations",
        "hr_compliance": "HR & People Ops",
        "general": "General Workflow",
    }

    def _build_system_injection(
        self,
        domains: list[str],
        rules: list[ApplicableRule],
        blocked_actions: list[str],
    ) -> str:
        domain_labels = ", ".join(
            self._DOMAIN_LABELS.get(d, d.replace("_", " ").title()) for d in domains
        )

        if not rules:
            return (
                f"## Workflow Automation Blueprint — {domain_labels}\n\n"
                "No specific compliance rules apply. Proceed with general best practices."
            )

        lines = [
            f"## Workflow Automation Blueprint — {domain_labels}",
            "",
            "You MUST comply with the following rules. Do NOT skip any rule.",
            "",
        ]
        for r in rules:
            flag = "🔴 CRITICAL" if r.risk_level == "critical" else ("🟠 HIGH" if r.risk_level == "high" else "🟡 MEDIUM")
            approval = " [HUMAN APPROVAL REQUIRED]" if r.human_approval_required else ""
            lines.append(f"### [{r.id}] {r.name} — {flag}{approval}")
            lines.append(f"RULE: {r.agent_rule}")
            lines.append("")

        if blocked_actions:
            lines.append("## Steps Requiring Human Sign-Off (cannot run automatically):")
            for action in blocked_actions:
                lines.append(f"  ✗ {action}")

        return "\n".join(lines)
