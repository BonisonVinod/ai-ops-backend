from app.database.base import Base
from app.database.session.db import engine

# Import models so SQLAlchemy registers them
from app.database.models.workflow import Workflow
from app.database.models.task import Task
from app.database.models.activity import Activity


def init_db():
    Base.metadata.create_all(bind=engine)
    print("Database tables created.")


if __name__ == "__main__":
    init_db()
