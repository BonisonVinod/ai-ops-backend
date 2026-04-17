import os
import json
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class ClassifierAgent:
    def classify(self, ticket_text: str) -> dict:
        prompt = f"""
Classify the following support ticket.

Return ONLY JSON in this format:
{{
    "category": "...",
    "priority": "low | medium | high"
}}

Ticket:
{ticket_text}
"""

        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": "You are a support ticket classifier."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0
            )

            content = response.choices[0].message.content.strip()
            return json.loads(content)

        except Exception as e:
            print(f"[ClassifierAgent Error]: {e}")

            return {
                "category": "unknown",
                "priority": "low"
            }
