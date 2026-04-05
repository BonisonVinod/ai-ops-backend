from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from app.database.base import Base


class Activity(Base):
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"))
    name = Column(String, nullable=False)
    description = Column(String)
    sequence_order = Column(Integer)

    # ✅ NEW FIELDS (safe nullable)
    intent = Column(String, nullable=True)
    execution_type = Column(String, nullable=True)
    automation_potential = Column(String, nullable=True)

    task = relationship("Task", back_populates="activities")
