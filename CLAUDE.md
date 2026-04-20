# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Run the server:**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Production (Render):**
```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 10000
```

**Initialize database:**
```bash
python app/database/init_db.py
```

**Run tests:**
```bash
python test_fix.py
```

**Start Celery worker (requires Redis):**
```bash
celery -A app.workers.tasks worker --loglevel=info
```

## Architecture

This is an **AI Operations Intelligence Platform** — a FastAPI monolith that analyzes SOPs (Standard Operating Procedures) and Job Descriptions to assess automation potential and ROI for "Digital Co-worker" deployment.

### Layer Overview

```
API Routes (app/routers/)
    ↓
Services (app/services/)        Agents (app/agents/)
    ↓                               ↓
Orchestrator (app/orchestrator/main_orchestrator.py)
    ↓
Database (SQLAlchemy/SQLite)    Vector DB (Qdrant)
```

### Key Data Flow

1. Document uploaded → `document_service.py` extracts text (PDF/DOCX/TXT)
2. Text chunked → `embedding_service.py` generates embeddings → stored in Qdrant
3. Workflow reconstructed via `workflow/reconstruction_engine.py`
4. SOP/JD analyzed via `agents/sop_analyzer.py` → ROI, precision score, pricing
5. Results persisted via `workflow_persistence_service.py` → SQLite

### Database Models (`app/database/models/`)

- **Workflow** — top-level container; has many Tasks
- **Task** — belongs to Workflow; has many Activities; stores role, tool, frequency, estimated_minutes
- **Activity** — leaf node; stores intent, execution_type, automation_potential, sequence_order

### Agent System (`app/agents/`)

Multi-agent pipeline coordinated by `orchestrator/main_orchestrator.py`:
- **classifier_agent.py** — classifies input as leave request / SOP / JD
- **sop_analyzer.py** — core analysis: automation potential, precision risk, ROI, pricing
- **decision_agent.py** — makes automation go/no-go decisions
- **response_agent.py** — generates natural language output
- **reviewer_agent.py** — validates agent outputs before returning

### Business Logic (critical — see PROJECT_STATE.md)

- **Pricing:** JD → 20% of Annual CTC; SOP → ₹25k–₹75k based on complexity
- **ROI Rule:** 20% salary rule — digital co-worker cost must be ≤ 20% of the role's annual salary
- **Precision Analysis:** Tasks flagged as error-sensitive get a precision score; high-precision tasks require human-in-the-loop approval before automation
- **Human-in-the-loop:** All final outputs require human approval step; orchestrator never auto-applies decisions

### Workflow Engine (`app/workflow/`)

- `reconstruction_engine.py` — rebuilds structured workflows from raw document chunks
- `observation_engine.py` — generates operational observations (bottlenecks, risks)
- `intelligence_engine.py` — AI-driven insights layered on top of workflow graph
- `graph_service.py` — DAG traversal and workflow graph management

### Memory & Vector System (`app/memory/`)

- Qdrant collection `"documents"` (vector size: 384, sentence-transformers embeddings)
- `sop_retriever.py` — semantic SOP lookup for similar past analyses
- Orchestrator stores outcomes with confidence > 70% back into vector store for learning

### Background Workers (`app/workers/tasks.py`)

Celery tasks (broker/backend: Redis):
- `process_document()` — async text extraction and embedding
- `generate_workflow_analysis()` — async workflow analysis

### Environment Variables

```
DATABASE_URL=sqlite:///./test.db     # or PostgreSQL URL in prod
REDIS_URL=redis://localhost:6379
QDRANT_URL=http://localhost:6333
OPENAI_API_KEY=<key>
```

### Key API Routes

| Route | Purpose |
|---|---|
| `POST /documents/upload` | Upload SOP/JD document, trigger full analysis pipeline |
| `POST /workflows/analyze` | Analyze raw text → workflow + observations |
| `POST /workflows/auto-generate` | Analyze + persist workflow |
| `POST /automation/start-automation` | Calculate complexity, architecture, timeline |
| `GET/POST /ai/` | AI operations including SOP analyzer |
| `GET /health` | Health check |

### Deployment

Deployed on **Render** (`render.yaml`). Python 3.11. CORS configured for `localhost:5173` (Vite frontend).
