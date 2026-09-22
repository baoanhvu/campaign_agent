# Marketing Insight Agent v2

AI agent trả lời các câu hỏi nghiệp vụ marketing: **dashboard hiệu quả chiến dịch**, **chẩn đoán chiến dịch**, **chân dung khách hàng**, và **hành động nâng cao CLV**.

Nguyên tắc thiết kế cốt lõi: **code tính toán — LLM chỉ diễn giải**. Mọi con số đến từ SQL, LLM phát số dưới dạng thẻ `{{F1.r1.romi}}`, hệ thống thay thẻ bằng giá trị thật trước khi hiển thị.

## Kiến trúc

```
Câu hỏi user
    │
    ▼
ROUTE → PLAN → COMPUTE → NARRATE → STREAMING VERIFY → VERIFY → JUDGE
    │         │           │              │                  │         │
  regex     playbook    SQL DB       auto-tag +          6 lớp     LLM
  classify  → metrics   (read-only)  substitute          anti-     judge
            → prompt                 tags                halluc    (async)
```

**Budget:** ≤ 2 LLM calls cho chat, 0 cho dashboard.

### Anti-Hallucination 6 lớp

| Lớp | Module | Mô tả | Chi phí |
|-----|--------|-------|---------|
| L0 | `verify/pipeline.py` | SQL validation (template bypass) | 0 LLM |
| L2 | `verify/numeric.py` | Numeric grounding — mọi số phải có evidence | 0 LLM |
| L3 | `verify/entity.py` | Entity grounding — tên riêng phải có trong DB | 0 LLM |
| L4 | `verify/stats_guard.py` | Stats guard — so sánh/causal phải có evidence | 0 LLM |
| L5 | `verify/judge.py` | LLM judge — kiểm tra entailment/contradiction | 1 LLM |
| L6 | `verify/pipeline.py` | Trust score — tổng hợp thành PASS/HEDGE/ABSTAIN/BLOCKED | 0 LLM |

Trust score = weighted sum of L0–L5, config tại `config/verify.yaml`.

## Tech Stack

- **Python 3.13+**, **FastAPI**, **Uvicorn** — web server & SSE streaming
- **PostgreSQL** + **SQLAlchemy** — database (read-only queries)
- **OpenAI-compatible LLM** (GreenNode MaaS / Qwen) — narration & judge
- **Pydantic Settings** — environment-driven config
- **Jinja2** — server-side templates cho dashboard/chat UI
- **Docker** — container deployment lên GreenNode AgentBase

## Project Structure

```
campaign_agent/
├── mkt-insight-agent-v2/          # Main application
│   ├── main.py                    # Production entrypoint (AgentBase SDK)
│   ├── run_local.py               # Local dev entrypoint (pure FastAPI)
│   ├── app/
│   │   ├── agent/                 # Orchestrator, router, planner, narrator, streaming
│   │   ├── api/                   # FastAPI routes: chat, dashboard, admin, conversations
│   │   ├── analytics/             # Dashboard metrics (KPIs, anomalies, funnel)
│   │   ├── data/                  # DB engine, catalog, read-only queries
│   │   ├── llm/                   # LLM client, insight interpreter, rate limiter
│   │   ├── prompts/               # Prompt loader (hot-reload from YAML)
│   │   ├── semantic/              # Metric catalog + SQL compiler
│   │   ├── telemetry/             # Trace logging
│   │   ├── verify/                # 6-layer anti-hallucination pipeline
│   │   ├── web/                   # Static assets + Jinja2 templates
│   │   ├── contracts.py           # Core dataclasses & protocols
│   │   ├── errors.py              # Typed error tree
│   │   ├── settings.py            # Pydantic settings (env-driven)
│   │   └── logging_.py            # Structured JSON logging
│   ├── config/
│   │   ├── playbooks/             # Intent → metric mapping (9 playbooks)
│   │   ├── semantic/              # Metric definitions + entity catalog
│   │   └── verify.yaml            # Anti-hallucination weights & thresholds
│   ├── prompts/                   # LLM prompt templates (YAML)
│   ├── etl/                       # Excel → PostgreSQL ETL pipeline
│   ├── tests/                     # 28 tests (pytest)
│   ├── evals/                     # Golden-set evaluation
│   ├── scripts/                   # Validation & deploy scripts
│   ├── Dockerfile
│   └── requirements.txt
└── README.md
```

## Quick Start

### Prerequisites

- Python 3.13+
- PostgreSQL (hoặc remote DB)
- LLM API key (GreenNode MaaS hoặc OpenAI-compatible)

### Install

```bash
cd mkt-insight-agent-v2
pip install -r requirements-local.txt
```

### Configure

```bash
cp .env.example .env
# Edit .env with your DB URL, LLM API key, and admin token
```

**Environment variables:**

| Variable | Description | Default |
|----------|-------------|---------|
| `MKT_DATABASE__URL` | PostgreSQL connection string | — |
| `LLM_API_KEY` | LLM API key | — |
| `LLM_BASE_URL` | LLM endpoint (OpenAI-compatible) | `https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1` |
| `LLM_MODEL` | Chat model | `qwen/qwen3.6-flash` |
| `LLM_JUDGE_MODEL` | Judge model | `qwen/qwen3.6-flash` |
| `MKT_ADMIN__TOKEN` | Admin API token | — |
| `APP_PROFILE` | Profile name (logged in traces) | `local` |
| `LOG_LEVEL` | Log level | `info` |

### Run locally

```bash
python run_local.py
# Server at http://127.0.0.1:8080
```

### Run with AgentBase SDK (production)

```bash
python main.py
# Server at http://0.0.0.0:8080
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (no DB) |
| GET | `/readyz` | Readiness check (DB + catalog) |
| GET | `/dashboard` | Dashboard UI |
| GET | `/chat` | Chat UI |
| GET | `/chat/{id}` | Chat with conversation ID |
| POST | `/api/chat` | Chat (SSE streaming) |
| GET | `/api/dashboard/data` | Dashboard metrics JSON |
| GET | `/api/dashboard/insights` | LLM-generated insights |
| POST | `/invocations` | Non-streaming gateway (for Zalo/external) |
| GET | `/api/trace/{id}` | Trace lookup |
| GET | `/api/admin/prompts` | List prompts (admin) |
| PUT | `/api/admin/prompts/{name}` | Update prompt (admin) |
| GET | `/api/admin/metrics` | List metrics (admin) |
| GET | `/api/admin/quality` | Quality dashboard (admin) |
| POST | `/api/admin/etl/run` | Run ETL pipeline (admin) |

## Testing

```bash
cd mkt-insight-agent-v2
pip install pytest
python -m pytest tests/ -v
```

28 tests covering: numeric grounding, semantic compiler, streaming verifier, judge severity, entity regex, VI number parsing, stats guard.

## Deployment (GreenNode AgentBase)

```bash
# Build & push Docker image
docker build --platform linux/amd64 -t <registry>/<image>:<tag> .
docker push <registry>/<image>:<tag>

# Update runtime
bash .claude/skills/agentbase/scripts/runtime.sh update <runtime-id> \
  --image "<registry>/<image>:<tag>" \
  --flavor runtime-s2-general-2x4 \
  --env-file .env \
  --from-cr
```

Console: https://aiplatform.console.vngcloud.vn/agent-runtime

## ETL Pipeline

```bash
# Load Excel → PostgreSQL raw tables → build mart
python -m etl.load_excel --file data/full_schema_mock.xlsx
python -m etl.build_marts
python -m etl.dq_checks   # Data quality validation
```

## Design Decisions

- **No LLM computes numbers** — mọi số từ SQL, LLM chỉ diễn giải
- **Playbook-based planning** — intent → metrics mapping qua YAML, tiết kiệm 1-2 LLM calls
- **Streaming với auto-tag** — quét bare numbers trong text, match với evidence, thay bằng thẻ
- **Degraded mode** — khi LLM unavailable, trả evidence dạng table (không crash)
- **Trace logging** — mọi câu hỏi ghi trace với trust score, latency, LLM calls

## License

Private project.
