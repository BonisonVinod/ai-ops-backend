from typing import List
from app.services.semantic_classifier import SemanticClassifier
from app.services.task_classifier import TaskClassifier

classifier = SemanticClassifier()
task_classifier = TaskClassifier()


def extract_aao(sentence: str):
    words = sentence.strip().split()

    if len(words) < 2:
        return {
            "actor": "Unknown",
            "action": sentence,
            "object": None,
            "tool": None
        }

    actor = words[0]
    action = words[1]
    obj = " ".join(words[2:]) if len(words) > 2 else None

    return {
        "actor": actor,
        "action": action,
        "object": obj,
        "tool": None
    }


def reconstruct_workflow(document_chunks: List[str]):

    workflow = {
        "name": "Generated Workflow",
        "tasks": []
    }

    for i, chunk in enumerate(document_chunks):

        task = {
            "name": f"Task {i+1}",
            "role": "Unknown",
            "tool": "Unknown",
            "frequency": "unknown",
            "estimated_minutes": 0,
            "activities": []
        }

        semantic = classifier.classify_activity(chunk)

        activity_obj = {
            "name": f"Activity {i+1}",
            "description": chunk,
            "sequence_order": 1,
            "intent": semantic["intent"],
            "execution_type": semantic["execution_type"],
            "automation_potential": semantic["automation_potential"]
        }

        task["activities"].append(activity_obj)

        task_type = task_classifier.classify_task(task["activities"])
        task["task_type"] = task_type

        workflow["tasks"].append(task)

    return {
        "workflow": workflow
    }
