from pydantic import BaseModel, ConfigDict


class ActivityCreate(BaseModel):
    task_id: int
    name: str
    description: str
    sequence_order: int


class ActivityResponse(BaseModel):
    id: int
    task_id: int
    name: str
    description: str
    sequence_order: int

    model_config = ConfigDict(from_attributes=True)
