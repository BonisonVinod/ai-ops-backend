from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.health import router as health_router
from app.api.routes.workflow_routes import router as workflow_router
from app.api.routes.task_routes import router as task_router
from app.api.routes.activity_routes import router as activity_router
from app.api.routes.document_routes import router as document_router
from app.api.routes.workflow_graph_routes import router as workflow_graph_router
from app.api.routes.workflow_intelligence_routes import router as workflow_intelligence_router
from app.api.routes.ai_ops_routes import router as ai_ops_router
from app.api.automation import router as automation_router
from app.api.codegen import router as codegen_router
from app.api.routes.sop_routes import router as sop_router

from app.database.base import Base
from app.database.session.db import engine

app = FastAPI()

Base.metadata.create_all(bind=engine)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(workflow_router)
app.include_router(task_router)
app.include_router(activity_router)
app.include_router(document_router)
app.include_router(workflow_graph_router)
app.include_router(workflow_intelligence_router)
app.include_router(automation_router, prefix="/automation")
app.include_router(codegen_router, prefix="/codegen")
app.include_router(sop_router)

# ✅ AI routes (important)
app.include_router(ai_ops_router, prefix="/ai")
