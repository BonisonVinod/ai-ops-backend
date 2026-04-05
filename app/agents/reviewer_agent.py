class ReviewerAgent:

    def review(self, ticket, decision, response):
        action = decision.get("action", "")
        confidence = decision.get("confidence", 0)

        # Normalize response
        if isinstance(response, dict):
            response_text = response.get("message", "")
        else:
            response_text = response

        # Rule 1
        if action == "resolve":
            return {
                "status": "rejected",
                "reason": "Direct resolution not allowed",
                "final_response": "We are currently investigating your issue."
            }

        # Rule 2
        if confidence < 50:
            return {
                "status": "rejected",
                "reason": "Low confidence",
                "final_response": "We are reviewing your request."
            }

        # Rule 3
        if not response_text or len(response_text.strip()) == 0:
            return {
                "status": "rejected",
                "reason": "Empty response",
                "final_response": "We are processing your request."
            }

        return {
            "status": "approved",
            "final_response": response_text
        }
