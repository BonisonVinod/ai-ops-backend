import os
import json
from typing import Dict
from openai import OpenAI
from app.agents.sop_analyzer import derive_factors, calculate_score, estimate_cost

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def analyze_sop(input_text: str) -> Dict:
    """
    Analyzes an SOP text, structures it via LLM, and calculates 
    deterministic scores and cost estimates.
    """
    
    # Define the updated LLM prompt with the new JSON schema
    prompt = f"""
    You are a senior operations consultant.
    Analyze the process and break it into steps.
    
    RULES:
    * Customer/user actions are NOT automation targets.
    * Use best practices for common things (passwords, retries, validations).
    * DO NOT ask unnecessary questions.
    * MAX 3 missing items.
    * Questions ONLY if absolutely required.
    * Include decision steps wherever validation or conditional logic exists.
    * Keep everything simple and business-friendly.

    INPUT: {input_text}

    RETURN ONLY JSON IN THIS FORMAT:
    {{
      "process_understanding": "A high-level summary of the workflow",
      "steps": [
        {{ 
          "step": "Step description", 
          "automation": "Automatable / Needs clarity / Manual", 
          "reason": "Why this classification?" 
        }}
      ],
      "missing_items": [
        {{ 
          "missing": "What is missing?", 
          "suggested_solution": "Best practice recommendation", 
          "question": "Optional question for the user" 
        }}
      ],
      "automation_plan": ["High-level solution steps"],
      "verdict": "A one-sentence summary of automation feasibility (e.g., 'High Potential' or 'Manual Intensive')"
    }}
    """

    # Call OpenAI to get the structured breakdown
    response = client.chat.completions.create(
        model="gpt-4o",  # Or your preferred model
        messages=[{"role": "system", "content": prompt}],
        response_format={"type": "json_object"}
    )
    
    analysis_result = json.loads(response.choices[0].message.content)

    # --- INTEGRATE DETERMINISTIC LOGIC ---
    # 1. Derive factors and calculate the deterministic automation score [2, 3]
    factors = derive_factors(input_text)
    score = calculate_score(factors)
    
    # 2. Estimate cost and effort based on the score and number of steps [3]
    num_steps = len(analysis_result.get("steps", []))
    cost_data = estimate_cost(score, num_steps)

    # --- MERGE RESULTS INTO FINAL SCHEMA ---
    # Injecting the requested fields: score, verdict (enhanced), and estimated_cost
    analysis_result["score"] = score
    analysis_result["estimated_cost"] = cost_data  # Includes 'effort' and 'cost' range
    
    # Ensure the verdict aligns with the deterministic score for consistency
    if score >= 85:
        analysis_result["verdict"] = f"High Potential: {analysis_result['verdict']}"
    elif score < 60:
        analysis_result["verdict"] = f"Manual Focus: {analysis_result['verdict']}"

    return analysis_result

# Add this to the bottom of test_fix.py
print(json.dumps(analyze_sop("This is a test process for password resets"), indent=2))
