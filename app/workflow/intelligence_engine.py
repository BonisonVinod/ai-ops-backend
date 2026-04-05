from typing import Dict


def parse_frequency(freq: str) -> int:
    """
    Convert frequency text to multiplier.
    """
    if not freq:
        return 1

    freq = freq.lower()

    if "daily" in freq:
        return 1

    if "weekly" in freq:
        return 1 / 7

    if "monthly" in freq:
        return 1 / 30

    if "hourly" in freq:
        return 24

    return 1


def analyze_workflow(workflow) -> Dict:

    total_time = 0
    manual_time = 0
    system_time = 0

    most_expensive_task = None
    max_time = 0

    automation_candidates = []

    for task in workflow.tasks:

        base_time = task.estimated_minutes or 0
        multiplier = parse_frequency(task.frequency)

        task_time = base_time * multiplier

        total_time += task_time

        if task.tool:
            system_time += task_time
        else:
            manual_time += task_time
            automation_candidates.append(task.name)

        if task_time > max_time:
            max_time = task_time
            most_expensive_task = task.name

    manual_percentage = 0

    if total_time > 0:
        manual_percentage = round((manual_time / total_time) * 100, 2)

    return {
        "workflow_time_minutes_per_day": round(total_time, 2),
        "manual_work_minutes_per_day": round(manual_time, 2),
        "system_work_minutes_per_day": round(system_time, 2),
        "manual_percentage": manual_percentage,
        "most_expensive_task": most_expensive_task,
        "automation_candidates": automation_candidates
    }
