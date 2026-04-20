from typing import Optional
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field


class ComplianceAnalysis(BaseModel):
    domain: str = Field(default="compliance")
    category: str = Field(
        description="labour_law | data_privacy | corporate_governance | environmental | hr_policy | regulatory_filing | other"
    )
    summary: str = Field(description="Plain-language summary of the compliance task/query")
    applicable_regulations: list[str] = Field(
        description="List of applicable laws/regulations (e.g., POSH Act, PDPB, Companies Act 2013)"
    )
    risk_level: str = Field(description="critical | high | medium | low")
    automation_feasibility: str = Field(description="high | medium | low")
    human_review_required: bool = Field(description="True if legal/regulatory precision mandates human sign-off")
    recommended_actions: list[str] = Field(description="Ordered list of compliance actions")
    deadline_sensitivity: bool = Field(description="True if there are statutory filing deadlines involved")
    penalty_exposure: Optional[str] = Field(default=None, description="Potential penalty if non-compliant")


_SYSTEM_PROMPT = """You are an expert Compliance AI specializing in Indian corporate and labour regulations.
Analyze the user's compliance query or task and respond with a structured JSON analysis.
Rules:
- Statutory filings, regulatory reports → always critical risk, human_review_required = true
- HR terminations, disciplinary actions → high risk, human_review_required = true
- Policy reviews, audit prep → medium risk, human_review_required = true
- Routine compliance tracking, reminders → low risk, human_review_required = false
Reference: Companies Act 2013, POSH Act, PDPB/DPDP Act, PF/ESI, SEBI, RBI.
"""

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM_PROMPT),
    ("human", "Analyze this compliance task:\n\n{query}"),
])


class ComplianceRouter:
    def __init__(self, model: str = "gpt-4o-mini"):
        self.llm = ChatOpenAI(model=model, temperature=0.1)
        self.parser = JsonOutputParser(pydantic_object=ComplianceAnalysis)
        self.chain = _PROMPT | self.llm | self.parser

    def route(self, query: str) -> dict:
        try:
            result = self.chain.invoke({"query": query})
            return {"status": "success", "domain": "compliance", "analysis": result}
        except Exception as e:
            return {"status": "error", "domain": "compliance", "message": str(e), "analysis": None}

    @staticmethod
    def can_handle(query: str) -> bool:
        keywords = {
            "compliance", "regulation", "legal", "policy", "labour law", "hr policy",
            "posh", "termination", "disciplinary", "gdpr", "data privacy", "pdpb",
            "companies act", "sebi", "rbi", "filing", "statutory", "penalty",
            "pf", "esi", "provident fund", "esic", "labour", "employment",
        }
        return any(kw in query.lower() for kw in keywords)
