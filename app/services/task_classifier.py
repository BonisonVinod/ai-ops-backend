class TaskClassifier:

    def classify_task(self, activities):

        if not activities:
            return "unknown"

        intent_counts = {}
        execution_counts = {}

        for act in activities:
            intent = act.get("intent", "unknown")
            execution = act.get("execution_type", "unknown")

            intent_counts[intent] = intent_counts.get(intent, 0) + 1
            execution_counts[execution] = execution_counts.get(execution, 0) + 1

        # Rule-based (deterministic systems)
        if execution_counts.get("system", 0) >= len(activities) * 0.6:
            return "rule_based"

        # Human dependent
        if intent_counts.get("decision", 0) > 0 or intent_counts.get("validation", 0) > 0:
            return "human_dependent"

        # AI based
        if intent_counts.get("communication", 0) > 0 or intent_counts.get("routing", 0) > 0:
            return "ai_based"

        return "rule_based"
