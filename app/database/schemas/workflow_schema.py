from pydantic import BaseModel


class WorkflowCreate(BaseModel):
    name: str
    description: str


class WorkflowResponse(BaseModel):
    id: int
    name: str
    description: str

    class Config:
        from_attributes = True
