## 🚨 UPDATE: ARCHITECTURE PIVOT

The system is evolving from a ticket-based AI Ops pipeline to a Process Intelligence & Automation Advisor.

New core layer being introduced:

👉 Process Intelligence Layer

This layer will:
- Understand SOP / process input
- Detect gaps in process definition
- Ask structured questions to complete missing details
- Evaluate automation feasibility

NOTE:
Existing layers (Classifier, Decision, Response) remain but are no longer the primary focus.
# AI Ops Platform — Architecture Blueprint

## 1. System Layers

### API Layer (FastAPI)
- Receives input (tickets, actions)
- Returns response
- No business logic

---

### Orchestrator Layer
- Controls flow between agents
- Decides:
  - which agent to call
  - execution order
  - retries / fallback

---

### Agent Layer

#### Classifier Agent
- Input: ticket text
- Output: category, priority

#### Decision Agent
- Input: ticket + context
- Output: next action (based on SOP + memory)

#### Response Agent
- Input: decision
- Output: response message

#### Reviewer Agent
- Input: response
- Output: approve / reject / corrected output

---

### Memory Layer (RAG)
- Stores:
  - past tickets
  - resolutions
  - escalation patterns
- Retrieves similar cases for better decisions

---

### Tool Layer
- SOP fetch
- Database access
- External API calls

---

### Feedback Layer (Future)
- Store outcomes
- Improve decision quality over time

---

## 2. Execution Flow

API → Orchestrator →  
Classifier →  
Decision (with memory) →  
Response →  
Reviewer →  
Final Output

---

## 3. Folder Structure

app/

 ├── api/
 ├── orchestrator/
 ├── agents/
 ├── memory/
 ├── tools/
 ├── services/
 ├── database/
 └── core/

---

## 4. Tech Stack

- Backend: FastAPI
- Database: PostgreSQL
- Vector DB: Chroma
- Embeddings: OpenAI
- Orchestration: Custom (no LangGraph initially)

---

## 5. Build Phases

### Phase 1: Foundation
- Create agent structure
- Build orchestrator skeleton
- Connect API to orchestrator

### Phase 2: Intelligence
- Implement classifier agent
- Implement decision agent

### Phase 3: Memory
- Add vector store
- Add retrieval to decision agent

### Phase 4: Output Quality
- Implement response agent
- Implement reviewer agent

### Phase 5: Optimization
- Feedback loop
- Confidence scoring
- Auto-improvement

---

## 6. Rules

- Do not skip phases
- Do not overcomplicate early
- Do not add extra agents initially
- Every step must be testable


Future Layer:
- JD → Workflow Mapping Layer

# Architecture Overview

## Current

Frontend (React)
↓
API Layer (FastAPI)
↓
SOP Analyzer (LLM + Rules)
↓
Response

---

## Key Components

### 1. LLM Layer
- Understands process
- Generates structured output

### 2. Rule Engine
- Scoring (deterministic)
- Question control
- Cost estimation

### 3. UI Layer
- Chat interface
- Structured cards
- Inline inputs

---

## Future Additions
- File parsing service
- Admin dashboard
- Workflow builder
- Integration layer
