from openai import OpenAI
import json
from datetime import datetime

client = OpenAI()


def calculate_leave_duration(start_date: str, end_date: str) -> int:
    fmt = "%Y-%m-%d"
    s = datetime.strptime(start_date, fmt)
    e = datetime.strptime(end_date, fmt)
    return max((e - s).days + 1, 0)


def ai_decision(request):
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a leave approval assistant. Return decision, reason and recommendation in JSON."
                },
                {
                    "role": "user",
                    "content": f"""
Employee: {request.get("employee_id")}
Leave Type: {request.get("leave_type")}
Start: {request.get("start_date")}
End: {request.get("end_date")}
Reason: {request.get("reason")}

Return:
{{"decision": "...", "reason": "...", "recommendation": "..."}}
"""
                }
            ]
        )

        return json.loads(response.choices[0].message.content)

    except Exception as e:
        return {
            "decision": "rejected",
            "reason": "AI failure",
            "recommendation": "Try again later"
        }


def decision_engine(request, balances):
    duration = calculate_leave_duration(
        request.get("start_date"),
        request.get("end_date")
    )

    leave_type = request.get("leave_type")
    employee_id = request.get("employee_id")

    available_balance = balances.get(employee_id, {}).get(leave_type, 0)

    # -------------------------------
    # RULE LAYER
    # -------------------------------
    if duration <= 0:
        return {
            "decision": "rejected",
            "reason": "Invalid leave duration",
            "recommendation": "Check dates and reapply"
        }

    if leave_type == "unpaid":
        return {
            "decision": "approved",
            "reason": "Unpaid leave allowed",
            "recommendation": "Proceed"
        }

    if available_balance >= duration:
        return {
            "decision": "approved",
            "reason": "Sufficient leave balance",
            "recommendation": "Proceed"
        }

    # -------------------------------
    # AI FALLBACK
    # -------------------------------
    return ai_decision(request)
