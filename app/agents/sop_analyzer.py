import json
import os
from typing import Dict
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def analyze_sop(input_text: str) -> Dict:
    prompt = f"""
You are the Strategic Lead for 'Agentic Mind'.
Analyze if the input is a Single SOP (Task) or a Job Description (Role).

--- RULE 1: PRICING (MANDATORY) ---
IF JOB DESCRIPTION (JD):
  - Estimate the average annual mid-level salary (CTC) in India for this specific role.
  - "setup_fee" = exactly 20% of that annual CTC (the 20% Salary Rule).
  - "setup_fee_basis" = "20% of ₹X,XX,XXX Annual CTC" with the actual number filled in.
  - If salary is unclear, assume ₹6,00,000 CTC → setup_fee = ₹1,20,000.
  - Use real Rupee numbers, never placeholders like "₹XX,XXX".

IF SOP (TASK):
  - "setup_fee" = between ₹25,000 and ₹75,000 based on number of logic steps and integrations.
  - "setup_fee_basis" = "SOP complexity-based pricing".
  - Always set bundling_advice to include: "Pro-Tip: Club up to 3 similar SOPs into one Digital Co-worker for better ROI."

--- RULE 2: PRECISION ANALYSIS (MANDATORY) ---
Assess for Error Sensitivity:
  - HIGH (precision_score 75-100): Financial calculations, payroll, legal compliance, medical decisions, regulatory filings, HR terminations. Always requires human approval.
  - MEDIUM (precision_score 40-74): Customer communications, data entry with business impact, reporting. Requires human review.
  - LOW (precision_score 0-39): Internal scheduling, data formatting, reminders, status updates. Spot checks sufficient.

--- RULE 3: HUMAN-IN-THE-LOOP (MANDATORY) ---
The Digital Co-worker handles EXECUTION ONLY. Humans approve all final outputs.
  - HIGH or MEDIUM sensitivity → human_approval_required = true (no exceptions).
  - LOW sensitivity → human_approval_required = false, specify spot-check cadence in approval_reason.

--- RULE 4: SKILL MAPPING (MANDATORY) ---
Extract specific 'Required AI Skills' — the actual technical capabilities the Digital Co-worker agent needs, drawn from our custom Python stack:
  - LangGraph nodes/edges (e.g., "LangGraph StateGraph for multi-step orchestration", "LangGraph conditional edge for approval routing")
  - LangChain tools/chains (e.g., "LangChain RetrievalQA chain", "LangChain StructuredOutputParser", "LangChain Tool for API calls")
  - Agent frameworks (e.g., "CrewAI agent with role specialization", "Pydantic AI for structured output validation")
  - Python libraries (e.g., "Python pdfminer for document extraction", "Python pandas for data processing", "SQLAlchemy for persistence")
  - LLM/embedding capabilities (e.g., "OpenAI GPT-4o for reasoning", "Sentence Transformers for semantic classification")
  - External API integrations (e.g., "Gmail API via Python", "Slack SDK", "Zoho/Tally REST connector")
List 4-8 specific skills.

--- RULE 5: TECHNICAL FEASIBILITY (MANDATORY) ---
Score 0-100 for how automatable this is using our custom LangGraph/LangChain Python stack:
  - 80-100: Straightforward LangGraph agent; standard LangChain tools cover all integrations; low custom node complexity.
  - 50-79: Requires custom LangGraph nodes, conditional edges, or multi-agent coordination via CrewAI; moderate build complexity.
  - 20-49: Needs complex stateful LangGraph workflows, specialized fine-tuning, or unreliable external APIs; significant engineering effort.
  - 0-19: Not reliably automatable today; heavy domain judgment, unstructured inputs, or no viable Python integration path.
List the specific LangGraph/LangChain/Python components that would be used.

--- RULE 6: SUBSCRIPTION TIERING (MANDATORY) ---
Based on precision_score and LangGraph build complexity, assign ONE plan:
  - Standard ₹9,999/month: LOW precision, single LangGraph agent, minimal custom nodes.
  - Pro ₹19,999/month: MEDIUM precision, multi-node LangGraph workflow, CrewAI coordination, or JDs with moderate complexity.
  - Enterprise ₹39,999/month: HIGH precision, multi-agent LangGraph StateGraph, financial/legal/medical tasks, complex JDs.
The "running_cost" field must match the chosen plan price exactly.

INPUT:
{input_text}

RETURN ONLY VALID JSON (no markdown, no extra text):
{{
  "type": "SOP | JD",
  "process_understanding": "Concise value proposition of automating this role/task.",
  "required_ai_skills": [
    "n8n HTTP Request Node",
    "OpenAI GPT-4o for text extraction",
    "Python pandas for data processing"
  ],
  "precision_analysis": {{
    "error_sensitivity": "High | Medium | Low",
    "precision_score": 85,
    "risk_category": "Financial | Legal | Medical | Operational | Administrative",
    "human_approval_required": true,
    "approval_reason": "Explain why human approval is or is not required."
  }},
  "technical_feasibility": {{
    "score": 75,
    "verdict": "Automatable with LangGraph + LangChain",
    "primary_tools": ["LangGraph", "LangChain", "OpenAI GPT-4o", "CrewAI"],
    "complexity_notes": "Key LangGraph node complexity, custom agent requirements, or integration challenges."
  }},
  "business_metrics": {{
    "automation_score": 85,
    "verdict": "Augmentation Recommended",
    "setup_fee": "₹1,20,000",
    "setup_fee_basis": "20% of ₹6,00,000 Annual CTC",
    "recommended_plan": "Pro",
    "running_cost": "₹19,999/month",
    "llm_option": "₹2,000 Pre-paid OR BYOK",
    "effort_level": "10-15 Days",
    "internal_justification": "Explain the salary benchmark and tier selection reasoning."
  }},
  "bundling_advice": "Specific advice on complementary tasks or roles that could be bundled."
}}
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a Financial Architect and Automation Risk Analyst for 'Agentic Mind'. "
                        "Apply all 6 rules strictly: 20% Salary Rule for JDs, precision scoring, "
                        "human-in-the-loop enforcement, AI skill mapping using LangGraph/LangChain/CrewAI/Pydantic AI, "
                        "technical feasibility scoring for a custom Python agent stack, "
                        "and subscription tier assignment. Output only valid JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        return {"status": "success", "analysis": json.loads(response.choices[0].message.content)}
    except Exception as e:
        return {"status": "error", "message": str(e)}
