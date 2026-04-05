import os
import json
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class ResponseAgent:

    def generate(self, ticket_text: str, decision: dict, classification: dict, sop: list) -> str:
        action = decision.get("action", "")

        # =========================
        # REQUEST MORE INFO
        # =========================
        if action == "request_more_info":

            # ✅ If SOP exists → convert activities into questions
            if sop:
                questions = []

                for wf in sop:
                    for task in wf.get("tasks", []):
                        for act in task.get("activities", []):

                            name = act.get("name", "").lower()

                            if "error" in name:
                                questions.append("Are you seeing any error message?")

                            elif "log" in name:
                                questions.append("Can you share logs or details of the issue?")

                            elif "submit" in name:
                                questions.append("What action were you performing when the issue occurred?")

                            elif "verify" in name:
                                questions.append("Can you confirm the steps you followed?")

                            elif "update" in name:
                                questions.append("When did this issue start?")

                # remove duplicates + limit
                questions = list(set(questions))[:3]

                if questions:
                    return " ".join(questions)

            # ✅ AI fallback (if no SOP or no match)
            prompt = f"""
You are a highly intelligent customer support agent.

Your job:
- Analyze the ticket carefully
- Ask ONLY the most relevant and specific questions
- Questions must directly depend on the issue in the ticket
- Avoid generic questions like "please provide more details"

Examples:
- If payment issue → ask transaction ID, date, amount
- If login issue → ask username, error message, last successful login
- If system error → ask error message, steps performed, timestamp

Ticket:
{ticket_text}

Return ONLY JSON:
{{
    "response": "..."
}}
"""

            ai_response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": "Ask precise support questions."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )

            try:
                content = ai_response.choices[0].message.content
                parsed = json.loads(content)
                return parsed.get("response", "Please provide more details.")
            except:
                return "Please provide more details."

        # =========================
        # INVESTIGATION
        # =========================
        elif action == "investigate":
            return "We are currently investigating your issue and will update you shortly."

        # =========================
        # RESOLUTION
        # =========================
        elif action == "resolve":
            return "Your issue has been resolved. Please check and confirm."

        # =========================
        # DEFAULT
        # =========================
        return "We are processing your request."
