def generate_observations(workflow: dict):
    """
    Generate simple operational insights from workflow structure.
    Phase-1 MVP placeholder.
    """

    observations = []

    tasks = workflow.get("tasks", [])

    if len(tasks) > 5:
        observations.append("Workflow contains many tasks — possible complexity")

    for task in tasks:
        if task.get("tool") == "Unknown":
            observations.append(
                f"Task '{task['name']}' does not specify a tool"
            )

    if not observations:
        observations.append("No obvious inefficiencies detected")

    return observations


# ✅ FINAL — INSIGHT ENGINE (SCORING + CLASSIFICATION)
def generate_insights_from_signals(signals: dict) -> dict:
    insights = []

    # ---- Complexity ----
    complexity = "Low"
    if signals["dependency_density"] > 1.5:
        complexity = "High"
    elif signals["dependency_density"] > 1:
        complexity = "Medium"

    insights.append({
        "type": "process",
        "message": f"Workflow complexity is {complexity}",
        "impact": "High" if complexity == "High" else "Medium" if complexity == "Medium" else "Low",
        "score": 3 if complexity == "High" else 2 if complexity == "Medium" else 1
    })

    # ---- Escalation ----
    if signals["escalation_count"] > 0:
        if complexity == "High":
            msg = "Escalations likely causing delays due to high complexity"
            impact = "High"
        else:
            msg = "Escalations present but manageable"
            impact = "Medium"

        insights.append({
            "type": "efficiency",
            "message": msg,
            "impact": impact,
            "score": 3 if impact == "High" else 2 if impact == "Medium" else 1
        })

    # ---- Role Distribution ----
    roles = signals.get("role_distribution", {})

    if roles.get("L1", 0) > roles.get("L2", 0):
        insights.append({
            "type": "efficiency",
            "message": "Majority of workload handled at L1 level",
            "impact": "Low",
            "score": 1
        })

    if roles.get("L2", 0) > 0 and roles.get("Engineering", 0) > 0:
        insights.append({
            "type": "risk",
            "message": "Dependency on L2 and Engineering detected",
            "impact": "High",
            "score": 3
        })

    # ---- Repetition ----
    if signals["possible_repetition"] > 0:
        insights.append({
            "type": "efficiency",
            "message": "Repeated steps detected in workflow",
            "impact": "Medium",
            "score": 2
        })

    # ---- SORT + LIMIT
    insights = sorted(insights, key=lambda x: x["score"], reverse=True)
    insights = insights[:5]

    # =====================================================
    # ✅ TASK CLASSIFICATION (NEW — IMPORTANT)
    # =====================================================

    total_tasks = signals.get("task_count", 0)
    escalation = signals.get("escalation_count", 0)
    repetition = signals.get("possible_repetition", 0)

    rule_based = int(total_tasks * 0.5)

    ai_based = int(
        (total_tasks * 0.3) +
        (escalation * 0.5) +
        (repetition * 0.3)
    )

    human = max(total_tasks - (rule_based + ai_based), 0)

    # Normalize (avoid overflow)
    total_classified = rule_based + ai_based + human
    if total_classified > total_tasks and total_classified > 0:
        scale = total_tasks / total_classified
        rule_based = int(rule_based * scale)
        ai_based = int(ai_based * scale)
        human = total_tasks - (rule_based + ai_based)

    summary = {
        "complexity": complexity,
        "task_classification": {
            "rule_based": rule_based,
            "ai_based": ai_based,
            "human_dependent": human
        },
        "confidence": 75
    }

    return {
        "insights": insights,
        "summary": summary
    }
