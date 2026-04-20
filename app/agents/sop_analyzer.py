import json
import os
from typing import Dict
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def analyze_sop(input_text: str) -> Dict:
    prompt = f"""
You are the Strategic Lead for 'Agentic Mind'. 
Analyze if the input is a Single SOP (Task) or a Job Description (Role).

PRICING RULES (MANDATORY):
1. IF JOB DESCRIPTION (JD):
   - Estimate the average annual mid-level salary (CTC) in India for this specific role.
   - Set "one_time_setup" as 20% of that annual salary.
   - If salary is unclear, assume a baseline of ₹6,00,000 CTC (Setup = ₹1,20,000).
   - Use real numbers, NOT "₹XX,XXX".

2. IF SOP (TASK):
   - Set "one_time_setup" between ₹25,000 and ₹75,000 based on complexity.
   - Always include a note: "Pro-Tip: You can club up to 3 similar SOPs into one Digital Co-worker for better ROI."

INPUT:
{input_text}

RETURN ONLY VALID JSON:
{{
  "type": "SOP or JD",
  "process_understanding": "Value proposition.",
  "agent_skills": ["Skill 1", "Skill 2"],
  "business_metrics": {{
    "score": 85,
    "verdict": "Augmentation Recommended",
    "one_time_setup": "₹1,20,000", 
    "monthly_subscription": "₹9,999",
    "llm_option": "₹2,000 Pre-paid OR BYOK",
    "effort_level": "10-15 Days",
    "internal_justification": "Explain the market salary used for the 20% calculation."
  }},
  "bundling_advice": "Specific advice on what other tasks could be clubbed with this one."
}}
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": "Financial Architect. Provide exact Rupee estimates based on 20% of annual market salary for JDs."},
                      {"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return {"status": "success", "analysis": json.loads(response.choices[0].message.content)}
    except Exception as e:
        return {"status": "error", "message": str(e)}
