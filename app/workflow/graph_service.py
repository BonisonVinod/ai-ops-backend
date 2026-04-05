from typing import Dict, List
from sqlalchemy.orm import Session, joinedload

from app.database.models import Workflow, Task, Activity


def build_workflow_graph(db: Session, workflow_id: int) -> Dict:
    """
    Build workflow graph from DB (with relationships)
    """

    workflow = db.query(Workflow).options(
        joinedload(Workflow.tasks).joinedload(Task.activities)
    ).filter(Workflow.id == workflow_id).first()

    if not workflow:
        return {"nodes": [], "edges": []}

    nodes: List[Dict] = []
    edges: List[Dict] = []

    workflow_node_id = f"workflow_{workflow.id}"

    # Workflow node
    nodes.append({
        "id": workflow_node_id,
        "type": "workflow",
        "label": workflow.name,
        "data": {
            "description": workflow.description
        }
    })

    for task in workflow.tasks:

        task_node_id = f"task_{task.id}"

        # Task node
        nodes.append({
            "id": task_node_id,
            "type": "task",
            "label": task.name,
            "data": {
                "role": task.role,
                "tool": task.tool,
                "frequency": task.frequency,
                "estimated_minutes": task.estimated_minutes
            }
        })

        # Edge: workflow → task
        edges.append({
            "source": workflow_node_id,
            "target": task_node_id,
            "type": "workflow-task"
        })

        # Sort activities by sequence
        activities = sorted(task.activities, key=lambda a: a.sequence_order or 0)

        previous_activity_id = None

        for activity in activities:

            activity_node_id = f"activity_{activity.id}"

            # Activity node
            nodes.append({
                "id": activity_node_id,
                "type": "activity",
                "label": activity.name,
                "data": {
                    "description": activity.description,
		    "intent": activity.intent,
		    "execution_type": activity.execution_type,
		    "automation_potential": activity.automation_potential
                }
            })

            # Edge: task → first activity
            if previous_activity_id is None:
                edges.append({
                    "source": task_node_id,
                    "target": activity_node_id,
                    "type": "task-activity"
                })
            else:
                # Edge: activity → next activity
                edges.append({
                    "source": previous_activity_id,
                    "target": activity_node_id,
                    "type": "activity-flow"
                })

            previous_activity_id = activity_node_id

    return {
        "nodes": nodes,
        "edges": edges
    }


# ✅ NEW FUNCTION — SIGNAL EXTRACTION (DO NOT MODIFY ABOVE CODE)
def extract_workflow_signals(nodes: List[Dict], edges: List[Dict]) -> Dict:
    total_nodes = len(nodes)
    total_edges = len(edges)

    task_count = 0
    activity_count = 0
    role_distribution = {}
    escalation_count = 0

    labels_seen = set()
    repetition_count = 0

    for node in nodes:
        label = (node.get("label") or "").lower()
        node_type = (node.get("type") or "").lower()
        data = node.get("data", {})

        # Task vs Activity (reliable now using type)
        if node_type == "task":
            task_count += 1
        elif node_type == "activity":
            activity_count += 1

        # Role detection (USE BACKEND DATA — IMPORTANT FIX)
        role = data.get("role", "System") if node_type == "task" else "System"
        role_distribution[role] = role_distribution.get(role, 0) + 1

        # Escalation detection
        if any(k in label for k in ["escalate", "escalation", "l2", "engineer"]):
            escalation_count += 1

        # Repetition detection
        if label in labels_seen:
            repetition_count += 1
        else:
            labels_seen.add(label)

    # Avoid division issues
    dependency_density = total_edges / total_nodes if total_nodes else 0
    avg_connections = (total_edges * 2) / total_nodes if total_nodes else 0

    return {
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "task_count": task_count,
        "activity_count": activity_count,
        "role_distribution": role_distribution,
        "escalation_count": escalation_count,
        "dependency_density": round(dependency_density, 2),
        "avg_connections_per_node": round(avg_connections, 2),
        "possible_repetition": repetition_count
    }
