# services/semantic_classifier.py

import re


class SemanticClassifier:

    def __init__(self):
        # keyword maps (simple but effective)
        self.intent_map = {
            "communication": ["email", "call", "notify", "send", "reply"],
            "data_entry": ["enter", "update", "fill", "input", "copy", "paste"],
            "data_processing": ["calculate", "generate", "compile", "create report"],
            "decision": ["decide", "check", "evaluate", "review", "approve"],
            "routing": ["assign", "route", "forward", "escalate"],
            "validation": ["verify", "validate", "confirm", "cross-check"],
            "system_action": ["upload", "download", "sync", "trigger"]
        }

    def classify_activity(self, text: str):
        text_lower = text.lower()

        intent = self.detect_intent(text_lower)
        execution = self.detect_execution(intent, text_lower)
        automation = self.detect_automation(intent, execution)

        return {
            "intent": intent,
            "execution_type": execution,
            "automation_potential": automation
        }

    def detect_intent(self, text):
        for intent, keywords in self.intent_map.items():
            for keyword in keywords:
                if keyword in text:
                    return intent
        return "unknown"

    def detect_execution(self, intent, text):
        # decision & approval → human
        if intent in ["decision", "validation"]:
            return "human"

        # communication → mixed
        if intent == "communication":
            return "ai_possible"

        # data entry → mostly system/automation
        if intent == "data_entry":
            return "system"

        # routing → automation candidate
        if intent == "routing":
            return "ai_possible"

        # fallback
        return "system"

    def detect_automation(self, intent, execution):
        if execution == "system":
            return "high"

        if intent in ["routing", "data_processing"]:
            return "high"

        if intent == "communication":
            return "medium"

        if intent in ["decision", "validation"]:
            return "low"

        return "medium"
