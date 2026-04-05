from app.agents.classifier_agent import ClassifierAgent
from app.agents.decision_agent import DecisionAgent
from app.agents.response_agent import ResponseAgent
from app.agents.reviewer_agent import ReviewerAgent
from app.memory.vector_store import store_ticket

# ✅ NEW IMPORT (Hybrid Decision Engine)
from app.services.decision_service import decision_engine


class Orchestrator:

    def __init__(self):
        self.classifier = ClassifierAgent()
        self.decision = DecisionAgent()
        self.response = ResponseAgent()
        self.reviewer = ReviewerAgent()

        # 👉 Temporary balance store (can be moved to DB later)
        self.employee_leave_balance = {
            "emp_001": {"annual": 10, "sick": 5, "unpaid": 999},
            "emp_002": {"annual": 2, "sick": 1, "unpaid": 999},
        }

    def run(self, ticket_text: str) -> dict:

        # -------------------------------
        # STEP 1 — CLASSIFICATION
        # -------------------------------
        classification = self.classifier.classify(ticket_text)

        # -------------------------------
        # STEP 2 — EXISTING DECISION (kept for compatibility)
        # -------------------------------
        agent_decision = self.decision.decide(ticket_text, classification)

        # -------------------------------
        # STEP 3 — PREPARE REQUEST FOR HYBRID ENGINE
        # -------------------------------
        # ⚠️ You can improve parsing later
        request_dict = self._extract_leave_request(ticket_text)

        # -------------------------------
        # STEP 4 — HYBRID DECISION ENGINE
        # -------------------------------
        decision_output = decision_engine(request_dict, self.employee_leave_balance)

        final_decision = decision_output.get("decision")
        reason = decision_output.get("reason")
        recommendation = decision_output.get("recommendation")

        # -------------------------------
        # STEP 5 — RESPONSE GENERATION
        # -------------------------------
        response = self.response.generate(
            ticket_text,
            {
                "decision": final_decision,
                "reason": reason,
                "recommendation": recommendation
            },
            classification,
            agent_decision.get("sop", [])
        )

        # -------------------------------
        # STEP 6 — REVIEW
        # -------------------------------
        review = self.reviewer.review(ticket_text, agent_decision, response)
        final_response = review["final_response"]

        # -------------------------------
        # STEP 7 — STORE LEARNING
        # -------------------------------
        if agent_decision.get("confidence", 0) > 70:
            store_ticket(
                ticket_text,
                {
                    "classification": classification,
                    "decision": final_decision,
                    "reason": reason,
                    "recommendation": recommendation,
                    "confidence": agent_decision.get("confidence"),
                    "status": "resolved"
                }
            )

        # -------------------------------
        # FINAL OUTPUT
        # -------------------------------
        return {
            "classification": classification,
            "decision": final_decision,
            "reason": reason,
            "recommendation": recommendation,
            "response": final_response,
            "review_status": review["status"]
        }

    # -------------------------------
    # HELPER — BASIC PARSER (TEMP)
    # -------------------------------
    def _extract_leave_request(self, text: str) -> dict:
        """
        ⚠️ This is a basic placeholder.
        Later you should replace this with:
        - NLP extraction
        - structured parser
        """

        return {
            "employee_id": "emp_001",  # temp default
            "leave_type": "annual" if "annual" in text.lower() else "sick",
            "start_date": "2026-04-10",
            "end_date": "2026-04-12",
            "reason": text
        }
