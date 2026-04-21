# BUILD REPORT — Agentic Factory Foundation + Execution API

**Build Date:** 2026-04-20  
**Build Mode:** Autonomous (`claude -y`)  
**Architect:** Claude Code (Sonnet 4.6)  
**Project:** ai-ops-backend — Transition from Analysis Tool → Agent Factory  
**Test Result:** ✅ 5/5 tests passed  
**API Layer:** ✅ 5 new endpoints live, server verified

---

## Mission

Transition "Agentic Mind" from a read-only SOP/JD *Analysis* tool into a functional *Agent Factory* — a system that takes an analysis report and autonomously builds, runs, and persists a multi-step agent pipeline to execute the recommended work.

---

## Architecture Overview

```
Analysis Report (from SOP Analyzer)
          │
          ▼
┌─────────────────────────────────────────────────────────┐
│                  AGENTIC FACTORY                        │
│                                                         │
│   composer.py (LangGraph StateMachine)                  │
│   ┌──────────────┐   ┌──────────────┐                  │
│   │ KnowledgeRouter│  │  Tool Selector│                  │
│   │ (domain rules) │  │ (LangChain)  │                  │
│   └──────┬───────┘   └──────┬───────┘                  │
│          │                  │                           │
│   ┌──────▼──────────────────▼──────┐                   │
│   │    StateGraph (6-8 nodes)      │                   │
│   │  ingest → load_knowledge       │                   │
│   │  → plan_actions → execute_tools│                   │
│   │  → [human_interrupt?]          │                   │
│   │  → synthesize → END            │                   │
│   └──────────────────┬─────────────┘                   │
│                      │                                  │
│              SqliteSaver (thread persistence)           │
└──────────────────────┼──────────────────────────────────┘
                       │
             Final Report / Audit Memo
```

---

## New File Tree

```
app/engine/
├── __init__.py                            ← exports build_factory_graph, run_factory
├── composer.py                            ← Master Agent Factory (LangGraph)
│
├── tools/
│   ├── __init__.py                        ← exports ALL_TOOLS list
│   ├── browser_tool.py                    ← DuckDuckGo web search
│   ├── document_tool.py                   ← PDF/DOCX/CSV/TXT extractor + CSV reader
│   └── code_tool.py                       ← Sandboxed Python exec + code generator
│
├── knowledge/
│   ├── __init__.py
│   ├── knowledge_router.py                ← Domain classifier + rule injector
│   ├── accounting_router.py               ← Specialist: Accounting LangChain chain
│   ├── compliance_router.py               ← Specialist: Compliance LangChain chain
│   └── rules/
│       ├── accounting_rules.json          ← Ground-truth: IndAS, TDS, GST, PF rules
│       └── it_compliance.json             ← Ground-truth: DPDP, ISO 27001, CERT-In, SEBI
│
└── agents/
    ├── __init__.py
    └── accounting_audit_agent.py          ← Prototype: Full accounting audit agent

tests/
├── data/
│   └── sample_ledger_q4_fy2526.csv        ← Dummy ledger (45 rows, Q4 FY26)
└── test_accounting_audit.py               ← Autonomous test suite (5 tests)

BUILD_REPORT.md                            ← This file
```

---

## Component Deep-Dives

### 1. Tool Layer (`app/engine/tools/`)

| File | Tool | Description | Safety |
|---|---|---|---|
| `browser_tool.py` | `browser_search` | DuckDuckGo Instant Answer API — no key needed | Read-only HTTP |
| `document_tool.py` | `extract_document` | PDF (pdfminer), DOCX (python-docx), TXT. Truncates at 10k chars | Read-only |
| `document_tool.py` | `read_csv_as_json` | CSV → JSON array. Limits to 200 rows. Used by audit agent for ledger reads | Read-only |
| `code_tool.py` | `execute_python` | Sandboxed `exec()` with stdout capture. Blocks: `subprocess`, `os.system`, `shutil.rmtree`, `eval`, `exec` | Sandboxed |
| `code_tool.py` | `generate_code` | GPT-4o-mini code generation from natural language description | LLM-backed |

All tools use the LangChain `@tool` decorator — they are usable in any LangChain agent executor or LangGraph tool node.

---

### 2. Knowledge Base (`app/engine/knowledge/`)

#### `knowledge_router.py` — KnowledgeRouter

The core domain intelligence injector. Pipeline:

```
text input
    │
    ├─► keyword_classify()   (fast, no LLM, covers 30+ keywords per domain)
    │         │
    ├─► LLM classify chain   (GPT-4o-mini, fallback to keywords on failure)
    │         │
    └─► merge domains → load_rules() → filter_rules() → build_system_injection()
                                                               │
                                                     KnowledgeContext returned
                                                     (injects into agent system prompt)
```

`KnowledgeContext` contains:
- `applicable_rules` — filtered `ApplicableRule` objects with `agent_rule` text
- `blocked_actions` — list of actions that must never be auto-executed
- `human_review_required` — True if any rule mandates it
- `system_prompt_injection` — ready-to-inject block for LLM system prompts

#### `rules/accounting_rules.json` — 8 Standards

| ID | Name | Risk | Human Required |
|---|---|---|---|
| IndAS-1 | Financial Statement Presentation | High | ✅ |
| IndAS-2 | Inventories | High | ✅ |
| IndAS-16 | Property, Plant & Equipment | Medium | ✅ |
| GST-Reconciliation | ITC Reconciliation | High | ✅ |
| TDS-194C | Contractor TDS | High | ✅ |
| TDS-194J | Professional Fee TDS | High | ✅ |
| PAYROLL-PF | Provident Fund Compliance | **Critical** | ✅ |
| AUDIT-TRAIL | Audit Trail (MCA 2023) | **Critical** | ✅ |

Blocked auto-actions: `post_journal_entry`, `file_gst_return`, `remit_tds`, `remit_pf`, `write_off_asset`, `approve_payment`

#### `rules/it_compliance.json` — 8 Standards

| ID | Name | Risk |
|---|---|---|
| DPDP-2023 | Digital Personal Data Protection Act | Critical |
| IT-ACT-43A | SPDI (Sensitive Personal Data) | Critical |
| ISO-27001 | ISMS Framework | High |
| SEBI-CSCRF | Cyber Security Resilience Framework | Critical |
| CERT-IN-2022 | 6-hour incident reporting, 180-day log retention | High |
| RBI-ITGF | IT Governance for Banks/NBFCs | Critical |
| VAPT-POLICY | Vulnerability Assessment & Penetration Testing | High |
| ACCESS-MGMT | Principle of Least Privilege | High |

---

### 3. The Composer — Agent Factory (`app/engine/composer.py`)

The master builder. Takes any task or analysis report → dynamically assembles a 7-node LangGraph StateMachine.

#### State (`FactoryState`)

```python
task_input          # the task / SOP description
analysis_report     # optional: SOP Analyzer output
thread_id           # SqliteSaver key for persistence
knowledge_domain    # "accounting" | "it_compliance" | "general"
knowledge_context   # serialized KnowledgeContext (injected into prompts)
domain_analysis     # output from AccountingRouter or ComplianceRouter
planned_actions     # tool names in execution order
planned_action_inputs  # corresponding inputs
current_action_index  # tracks resume point after interrupt
tool_results        # Annotated[list, add] — append-only accumulator
human_review_required  # bool — set by knowledge rules
high_risk_action_pending  # which tool triggered the interrupt
human_feedback      # CA/human reviewer response
final_output        # synthesized report
messages            # Annotated[list, add] — full conversation log
```

#### Graph Flow

```
START
  → ingest_analysis        LLM: parse task + report, extract domain hint
  → load_knowledge         KnowledgeRouter + AccountingRouter/ComplianceRouter
  → plan_actions           LLM: select tools + inputs for the task
  → execute_tools          Run tools; stop before high-risk ones
  → [conditional]
      if human_review_required OR high_risk_tool pending:
        → human_interrupt  ← Graph PAUSES here (interrupt_before)
        → [conditional]
            if high_risk tool pending: → execute_high_risk_tools
            else: → synthesize
      else:
        → synthesize
  → synthesize             GPT-4o-mini produces final report
  → END
```

#### Human Interrupt Design

Two classes of interrupts:
1. **Knowledge-triggered**: `human_review_required=True` from domain rules (e.g., TDS, payroll)
2. **Tool-triggered**: `execute_python` or `generate_code` detected in plan — always interrupt before running

Resume protocol (HTTP API pattern):
```
POST /engine/run    { task, thread_id }
  → 202 { status: "awaiting_review", thread_id, review_payload }

POST /engine/resume { thread_id, human_feedback: "approved: ..." }
  → 200 { final_output, audit_memo }
```

#### Thread Persistence (SqliteSaver)

`SqliteSaver.from_conn_string(db_path)` writes a checkpoint after every node.
Thread state survives: server restarts, HTTP timeouts, async human review delays.

```python
# First call (pauses at human_interrupt)
result = run_factory(task="Audit payroll", thread_id="thread-001")

# Hours later — resume after CA review
result = run_factory(
    task="Audit payroll",
    thread_id="thread-001",
    human_feedback="approved: PF deductions verified by CFO"
)
```

---

### 4. Prototype Agent (`app/engine/agents/accounting_audit_agent.py`)

`AccountingAuditAgent` — a fully wired, pre-assembled 6-node audit pipeline.

#### Graph (Purpose-Built for Accounting Audits)

```
START
  → read_ledger           read_csv_as_json tool → parse 45+ rows
  → consult_knowledge     KnowledgeRouter → 8 accounting standards injected
  → analyze_ledger        GPT-4o-mini + rules → TDS/GST/PF/IndAS flags
  → propose_changes       GPT-4o-mini → corrective journal entries per flag
  → human_approval_gate   ← interrupt_before: CA MUST review before proceeding
  → generate_memo         GPT-4o-mini → formal audit memo
  → END
```

#### Demonstrated on Q4 FY 2025-26 Ledger (45 transactions)

Actual flags found by the agent on the dummy CSV:

| Type | Flag |
|---|---|
| TDS-194J | ₹85,000 to Infosys Ltd — TDS not deducted |
| TDS-194C | ₹45,000 to Ramesh Kumar — TDS not deducted |
| TDS-194C | ₹32,000 to Akash Singh — TDS not deducted |
| GST-Reconciliation | Contractor payments with GST but no ITC recorded |
| PAYROLL-PF | Arjun Das (Basic ₹15,500) — PF not deducted |
| IndAS-1 | Event Management ₹1,80,000 — materiality threshold exceeded |

9 corrective journal entry proposals generated, then paused for CA review.

---

## Test Results (`tests/test_accounting_audit.py`)

```
Test 1: CSV Read Tool          ✅ PASSED — 45 rows, 11 columns parsed
Test 2: KnowledgeRouter        ✅ PASSED — 8+8 rules, domain classification, injection
Test 3: Graph Structure        ✅ PASSED — 6 nodes verified, interrupt_before confirmed
Test 4: End-to-End + Interrupt ✅ PASSED — Phase 1: flags + proposals; Phase 2: memo
Test 5: Code Sandbox Safety    ✅ PASSED — subprocess/os.system/eval blocked

Total: 5/5 PASSED
```

**Test 4 Highlights:**
- Phase 1 runtime: ~30–37s (3 LLM calls: classify → analyze → propose)
- Phase 2 runtime: ~15–20s (resume → human_approval_gate → generate_memo)
- Audit memo: ~2,800 chars, formally structured
- Thread persistence: verified via SqliteSaver with temp file DB

---

## New Dependencies

Added to `requirements.txt`:

| Package | Version | Purpose |
|---|---|---|
| `langchain` | ≥1.2.0 | Core orchestration, `@tool` decorator |
| `langchain-openai` | ≥1.1.0 | `ChatOpenAI`, OpenAI LLM bindings |
| `langchain-community` | ≥0.4.0 | Community tools and integrations |
| `langchain-core` | ≥1.3.0 | `ChatPromptTemplate`, `JsonOutputParser` |
| `langgraph` | ≥1.1.0 | `StateGraph`, `END`, `START`, `interrupt` |
| `langgraph-checkpoint-sqlite` | ≥3.0.0 | `SqliteSaver` thread persistence |

**Installed versions (as of 2026-04-20):**
- LangChain 1.2.15
- LangGraph 1.1.8
- langgraph-checkpoint-sqlite 3.0.3

---

## Integration Guide

### Wire into existing SOP Analyzer

```python
from app.agents.sop_analyzer import analyze_sop
from app.engine.agents.accounting_audit_agent import AccountingAuditAgent

# Step 1: Analyze the SOP/JD
analysis = analyze_sop(raw_text)

# Step 2: If accounting domain, trigger the audit agent
if analysis["analysis"]["type"] == "SOP":
    agent = AccountingAuditAgent()
    result = agent.run(csv_file_path, "Q4 FY 2025-26")
```

### API Routes (Now Live)

All routes are registered in `app/main.py` and verified on server startup.

```
POST /engine/run                 Run factory for any task
POST /engine/resume              Resume thread after human interrupt
GET  /engine/status/{thread_id}  Inspect persisted thread state
POST /engine/audit/run           Upload CSV + start accounting audit
POST /engine/audit/resume        Resume audit after CA review

POST /sop/analyze                Analyze SOP/JD (static spec, no execution)
POST /sop/analyze-and-run        Analyze + immediately run in the factory
```

### Full API Flow (Analyze → Run → Human Review → Resume)

```
# Step 1: Analyze + run
POST /sop/analyze-and-run
  Body: { "input": "Process monthly TDS reconciliation", "auto_run": true }
  Returns: { "status": "awaiting_review", "thread_id": "sop-abc123", ... }

# Step 2: Human reviews the output, then resumes
POST /engine/resume
  Body: { "thread_id": "sop-abc123", "task": "...", "human_feedback": "approved" }
  Returns: { "status": "completed", "final_output": "..." }
```

### Audit-Specific Flow (CSV Upload)

```
# Step 1: Upload ledger CSV
POST /engine/audit/run
  Form: file=<ledger.csv>, audit_period="Q4 FY 2025-26"
  Returns: { "status": "awaiting_review", "thread_id": "audit-xyz", "tds_flags": [...] }

# Step 2: CA reviews flags + proposals, then approves
POST /engine/audit/resume
  Body: { "thread_id": "audit-xyz", "human_feedback": "approved: all TDS entries verified" }
  Returns: { "status": "completed", "audit_memo": "..." }
```

### CORS + Frontend

The `factory_checkpoints.db` and `audit_checkpoints.db` files are auto-created at the project root on first run.  
For production (Render), set `FACTORY_DB_PATH=/tmp/factory.db` and `AUDIT_DB_PATH=/tmp/audit.db`.

---

## Business Rules Enforced

| Rule | Enforcement Point |
|---|---|
| No auto-filing of TDS/GST/PF | `blocked_auto_actions` in accounting_rules.json |
| Human sign-off on all payroll | `PAYROLL-PF.human_approval_required = true` |
| No code execution without review | `_HIGH_RISK_TOOLS` in composer.py |
| Audit trail for all agent actions | `messages` field — append-only log in state |
| No PII auto-export | `it_compliance.blocked_auto_actions` |
| CA review gate on journal entries | `interrupt_before=["human_approval_gate"]` |

---

## Known Limitations & Next Steps

| Item | Status | Next Step |
|---|---|---|
| LLM JSON parsing occasionally produces non-JSON output | Handled with try/except fallback | Add structured output with function calling |
| In-memory SQLite for tests | Intentional (no disk state) | Production uses file-based or PostgreSQL |
| `accounting_rules.json` is static | Functional for v1 | Connect to live IndAS/CBDT update feed |
| `it_compliance.json` covers India only | Intentional scope | Add GDPR, SOC2 modules for international |
| ~~No API routes wired yet~~ | ✅ Done — 5 endpoints live | — |
| Composer LLM plan can select wrong tool | Fallback to `browser_search` | Add few-shot examples to `_PLAN_PROMPT` |
| `analyze-and-run` calls LLM twice (analyze + factory) | Acceptable for v1 | Cache analysis result in thread state |
| File upload CSV saved to `/tmp` | Works on Render | Set retention policy or stream directly |

---

## Cumulative File Manifest

| File | Role | Session |
|---|---|---|
| `app/engine/composer.py` | LangGraph Agent Factory — 7-node StateMachine | 1 |
| `app/engine/tools/browser_tool.py` | DuckDuckGo web search | 1 |
| `app/engine/tools/document_tool.py` | PDF/DOCX/CSV/TXT extractor | 1 |
| `app/engine/tools/code_tool.py` | Sandboxed Python exec + code gen | 1 |
| `app/engine/knowledge/knowledge_router.py` | Domain classifier + rule injector | 2 |
| `app/engine/knowledge/accounting_router.py` | Accounting LangChain chain | 1 |
| `app/engine/knowledge/compliance_router.py` | Compliance LangChain chain | 1 |
| `app/engine/knowledge/rules/accounting_rules.json` | 8 IndAS/TDS/GST/PF standards | 2 |
| `app/engine/knowledge/rules/it_compliance.json` | 8 DPDP/ISO27001/SEBI standards | 2 |
| `app/engine/agents/accounting_audit_agent.py` | Prototype 6-node audit agent | 2 |
| `app/api/routes/engine_routes.py` | **NEW** — 5 execution API endpoints | 3 |
| `app/api/routes/sop_routes.py` | Upgraded + analyze-and-run endpoint | 3 |
| `app/services/agent_spec_service.py` | Upgraded + factory_run_spec output | 3 |
| `tests/data/sample_ledger_q4_fy2526.csv` | Dummy Q4 FY26 ledger (45 rows) | 2 |
| `tests/test_accounting_audit.py` | Autonomous test suite (5/5 pass) | 2 |

---

*Built autonomously by Claude Code across 3 sessions on 2026-04-20.*
