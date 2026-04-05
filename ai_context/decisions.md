# Decisions Log

- Backend framework: FastAPI
- Database: PostgreSQL
- Architecture: Agent-based system
- Orchestrator: Custom (not LangGraph initially)
- Memory: RAG-based system
- Vector DB: Chroma (initial)
- Embeddings: OpenAI (can change later)

## Rules

- No overengineering early
- Build in phases
- Each step must be testable
- Keep agents simple initially


## Decision: Pivot to Process Intelligence System

### Context
Initial system was designed for AI-driven ticket handling using SOP + RAG.

### Problem
This approach assumes SOPs are already complete and automation-ready, which is not true in real-world scenarios.

### Decision
Shift focus to building a system that:

- Understands incomplete or unstructured SOPs
- Identifies missing operational details
- Asks intelligent questions to complete the process
- Evaluates automation feasibility before execution

### Impact
- Existing pipeline becomes secondary (execution layer)
- New core system will focus on process understanding and gap detection

### Status
Approved and in progress


# Product Decisions

## 1. Product Positioning
We are NOT building:
- A chatbot
- A fully autonomous AI

We ARE building:
→ Process Intelligence + Automation Advisor

---

## 2. Question Strategy
- Questions only when absolutely required
- Max 2–3 questions
- No open-ended questioning
- No technical jargon
- Replace most questions with recommendations

---

## 3. Missing Information Handling
Instead of:
❌ "Missing info"

We use:
✔ Missing + Suggested Solution + Optional Question

---

## 4. Automation Scope
- Customer/user actions are NOT automation targets
- Only internal/system steps are evaluated

---

## 5. Scoring Model
- Deterministic (rule-based)
- NOT dependent on AI randomness
- Based on:
  - Process clarity
  - Inputs
  - Decision logic
  - System access
  - Human dependency

---

## 6. UX Philosophy
- Consultant-style output
- Structured, not chat-heavy
- Minimal friction
- Actionable insights

---

## 7. Cost Strategy
- Show ranges (not exact pricing)
- Based on complexity + steps
- Used for qualification, not billing

---

## 8. Product Flow
Analyze → Insight → Recommend → (Future) Build

NOT:
Analyze → Ask 100 questions → Confuse user
