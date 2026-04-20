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
        }


# ---------------------------------------------------------------------------
# Domain classification (LLM-backed)
# ---------------------------------------------------------------------------

class DomainClassification(BaseModel):
    domains: list[str] = PydanticField(
        description="List of applicable domains from: accounting, it_compliance, hr_compliance, general"
    )
    confidence: float = PydanticField(description="0.0 to 1.0")
    reasoning: str = PydanticField(description="Brief explanation of domain selection")


_CLASSIFY_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "Classify the given SOP or task description into one or more knowledge domains. "
        "Available domains: accounting, it_compliance, hr_compliance, general. "
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

        return KnowledgeContext(
            domains=domains,
            applicable_rules=all_rules,
            blocked_actions=list(set(all_blocked)),
            auto_approvable_actions=list(set(all_auto)),
            variance_thresholds=all_thresholds,
            system_prompt_injection=prompt_injection,
            human_review_required=human_required,
        )

    def get_context_dict(self, text: str, planned_actions: Optional[list[str]] = None) -> dict:
        return self.get_context(text, planned_actions).to_dict()

    # ------------------------------------------------------------------
    # Domain classification
    # ------------------------------------------------------------------

    def _classify_domains(self, text: str) -> list[str]:
        # Fast keyword pre-check
        keyword_domains = self._keyword_classify(text)

        try:
            result = self.classify_chain.invoke({"text": text})
            llm_domains = result.get("domains", []) if isinstance(result, dict) else []
            merged = list(set(keyword_domains + [d for d in llm_domains if d in DOMAIN_REGISTRY]))
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

    def _build_system_injection(
        self,
        domains: list[str],
        rules: list[ApplicableRule],
        blocked_actions: list[str],
    ) -> str:
        if not rules:
            return "No specific domain rules apply. Proceed with general best practices."

        lines = [
            f"## ACTIVE DOMAIN RULES ({', '.join(d.upper() for d in domains)})",
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
            lines.append("## BLOCKED ACTIONS (never execute autonomously):")
            for action in blocked_actions:
                lines.append(f"  ✗ {action}")

        return "\n".join(lines)
