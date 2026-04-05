from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from app.database.base import Base


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"))
    name = Column(String, nullable=False)
    role = Column(String)
    tool = Column(String)
    frequency = Column(String)
    estimated_minutes = Column(Integer)

    workflow = relationship("Workflow", back_populates="tasks")
    activities = relationship("Activity", back_populates="task")
