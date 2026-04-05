from pydantic import BaseModel, ConfigDict


class TaskCreate(BaseModel):
    workflow_id: int
    name: str
    role: str
    tool: str
    frequency: str
    estimated_minutes: int


class TaskResponse(BaseModel):
    id: int
    workflow_id: int
    name: str
    role: str
    tool: str
    frequency: str
    estimated_minutes: int

    model_config = ConfigDict(from_attributes=True)
