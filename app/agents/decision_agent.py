import os
import json
from openai import OpenAI
from app.memory.retriever import Retriever
from app.memory.sop_retriever import SOPRetriever

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class DecisionAgent:

    def __init__(self):
        self.retriever = Retriever()
        self.sop = SOPRetriever()

    def decide(self, ticket_text: str, classification: dict) -> dict:

        # -------------------------------
        # 1. Get similar past tickets (RAG)
        # -------------------------------
        similar_cases = self.retriever.get_context(ticket_text)
        context = "\n".join(similar_cases) if similar_cases else "No similar past cases."

        # -------------------------------
        # 2. Get ALL SOP workflows
        # -------------------------------
        all_workflows = self.sop.get_workflows()

        # -------------------------------
        # 3. AI-based SOP selection
        # -------------------------------
        selection_prompt = f"""
You are an expert in operations workflows.

Given a customer ticket and list of SOP workflows,
select ONLY the workflows that are relevant.

Return ONLY JSON:
{{
    "relevant_workflows": ["workflow_name1", "workflow_name2"]
}}

Ticket:
{ticket_text}

Available SOPs:
{[wf.get("workflow_name") for wf in all_workflows]}
"""

        try:
            selection_response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": "Select relevant SOP workflows."},
                    {"role": "user", "content": selection_prompt}
                ],
                temperature=0
            )

            selected = json.loads(selection_response.choices[0].message.content)
            names = selected.get("relevant_workflows", [])

            workflows = [
                wf for wf in all_workflows
                if wf.get("workflow_name") in names
            ]

        except:
            workflows = []

        # -------------------------------
        # 4. Prepare SOP context
        # -------------------------------
        sop_context = json.dumps(workflows, indent=2) if workflows else "No SOP available"

        # -------------------------------
        # 5. Decision Prompt
        # -------------------------------
        prompt = f"""
You are an operations decision engine for a support system.

Your goal:
- Analyze the ticket
- Use classification, past cases, and SOP workflows
- Decide the safest and most appropriate next step

IMPORTANT RULES:
- Do NOT take irreversible actions without verification
- Always prefer investigation before action
- Do NOT assume customer claims are correct
- Follow SOP workflows when relevant

Allowed action types:
- investigate_issue
- request_more_info
- escalate_to_team
- resolve_issue

Return ONLY JSON:
{{
    "action": "...",
    "reason": "...",
    "confidence": 0-100
}}

Ticket:
{ticket_text}

Classification:
{classification}

Similar past cases:
{context}

SOP Workflows:
{sop_context}
"""

        # -------------------------------
        # 6. Call LLM for decision
        # -------------------------------
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "You are a smart operations decision engine."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )

        content = response.choices[0].message.content

        # -------------------------------
        # 7. Parse response
        # -------------------------------
        try:
            parsed = json.loads(content)

            return {
                "action": parsed.get("action"),
                "reason": parsed.get("reason"),
                "confidence": parsed.get("confidence"),
                "sop": workflows
            }

        except:
            return {
                "action": "manual_review",
                "reason": "Parsing failed",
                "confidence": 50,
                "sop": workflows
            }
