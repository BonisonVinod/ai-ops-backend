from app.database.base import Base
from app.database.session.db import engine

# Import all models so SQLAlchemy registers them before create_all
from app.database.models.workflow import Workflow
from app.database.models.task import Task
from app.database.models.activity import Activity
from app.database.models.subscription import Subscription
from app.database.models.license import License


def init_db():
    Base.metadata.create_all(bind=engine)
    print("Database tables created.")


if __name__ == "__main__":
    init_db()
