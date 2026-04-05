def generate_agent_spec(insights: dict):

    # Safety: handle string JSON
    if isinstance(insights, str):
        import json
        insights = json.loads(insights)

    steps = insights.get("steps", [])

    workflow = []
    previous_output = "input_data"

    for i, step in enumerate(steps):
        step_text = step.get("step", "")
        step_name = step_text.lower()

        # -----------------------------
        # SMART STEP TYPE DETECTION
        # -----------------------------
        is_decision = any(keyword in step_name for keyword in [
            " if ", " if(", " whether ", " else ", " based on "
        ])

        if is_decision:
            step_type = "decision"
        elif any(word in step_name for word in ["validate", "verify", "check format"]):
            step_type = "validate"
        elif any(word in step_name for word in ["send", "call", "trigger", "notify"]):
            step_type = "api_call"
        elif any(word in step_name for word in ["store", "persist", "save", "update", "write"]):
            step_type = "database"
        elif any(word in step_name for word in ["generate", "create", "render"]):
            step_type = "generate"
        else:
            step_type = "transform"

        output_name = f"step_{i+1}_output"

        step_data = {
            "id": f"step_{i+1}",
            "name": step_text,
            "type": step_type,
            "input": [previous_output],
            "output": [output_name]
        }

        # -----------------------------
        # DECISION HANDLING
        # -----------------------------
        if step_type == "decision":

            step_data["condition"] = {
                "key": f"step_{i+1}_decision",
                "label": step_text,
                "operator": "check",
                "value": True
            }

            step_data["true_next"] = f"step_{i+2}" if i + 1 < len(steps) else None
            step_data["false_next"] = f"step_{i+1}_fallback"

            # Add fallback step
            fallback_step = {
                "id": f"step_{i+1}_fallback",
                "name": "Request missing or invalid input from user",
                "type": "user_input",
                "input": [previous_output],
                "output": [f"step_{i+1}_fallback_output"]
            }

            workflow.append(step_data)
            workflow.append(fallback_step)

        else:
            step_data["condition"] = None
            workflow.append(step_data)

        previous_output = output_name

    return {
        "goal": insights.get("process_understanding", ""),
        "inputs": ["input_data"],
        "workflow": workflow,
        "outputs": [previous_output]
    }
