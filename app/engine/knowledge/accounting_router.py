from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field


class AccountingAnalysis(BaseModel):
    domain: str = Field(default="accounting")
    category: str = Field(description="payroll | tax | financial_reporting | audit | budgeting | other")
    summary: str = Field(description="Plain-language summary of the accounting task/query")
    automation_feasibility: str = Field(description="high | medium | low")
    risk_level: str = Field(description="high | medium | low")
    recommended_actions: list[str] = Field(description="Ordered list of recommended steps")
    human_review_required: bool = Field(description="True if financial precision mandates human sign-off")
    compliance_flags: list[str] = Field(default_factory=list, description="Applicable standards: GST, TDS, IndAS, etc.")


_SYSTEM_PROMPT = """You are an expert Accounting AI specializing in Indian financial regulations.
Analyze the user's accounting query or task and respond with a structured JSON analysis.
Rules:
- Payroll, TDS, GST filings → always high risk, human_review_required = true
- Financial statements, audit reports → high risk, human_review_required = true
- Budget forecasting, expense categorization → medium risk
- Routine data entry, invoice logging → low risk, human_review_required = false
Map applicable Indian standards: GST, TDS sections, IndAS/AS, Companies Act 2013.
"""

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM_PROMPT),
    ("human", "Analyze this accounting task:\n\n{query}"),
])


class AccountingRouter:
    def __init__(self, model: str = "gpt-4o-mini"):
        self.llm = ChatOpenAI(model=model, temperature=0.1)
        self.parser = JsonOutputParser(pydantic_object=AccountingAnalysis)
        self.chain = _PROMPT | self.llm | self.parser

    def route(self, query: str) -> dict:
        try:
            result = self.chain.invoke({"query": query})
            return {"status": "success", "domain": "accounting", "analysis": result}
        except Exception as e:
            return {"status": "error", "domain": "accounting", "message": str(e), "analysis": None}

    @staticmethod
    def can_handle(query: str) -> bool:
        keywords = {
            "payroll", "salary", "tds", "gst", "invoice", "tax", "audit",
            "balance sheet", "profit", "loss", "expense", "revenue", "ledger",
            "accounts payable", "accounts receivable", "depreciation", "budget",
            "financial", "journal", "voucher", "tally", "zoho books",
        }
        return any(kw in query.lower() for kw in keywords)
