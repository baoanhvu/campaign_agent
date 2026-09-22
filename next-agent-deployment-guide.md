# Tài liệu triển khai chi tiết — Marketing Insight Agent (thế hệ mới)

> Tài liệu self-contained A→Z: từ scaffold đến deploy lên GreenNode AgentBase.
> Sử dụng **9 skill** từ `vngcloud/greennode-agentbase-skills` (trừ `teardown`),
> tích hợp đầy đủ **giao diện UI** và **hệ thống chống hallucination 7+1 lớp**.
> Cả local và production dùng chung một PostgreSQL và một LLM model trên GreenNode.

---

## Mục lục

1. [Mục tiêu và nguyên tắc](#1-mục-tiêu-và-nguyên-tắc)
2. [Skills Index — 9 skill](#2-skills-index--9-skill)
3. [Lifecycle Map](#3-lifecycle-map)
4. [Cấu hình cố định (IAM + DB + LLM)](#4-cấu-hình-cố-định-iam--db--llm)
5. [Phase 0 — GET STARTED](#phase-0--get-started)
6. [Phase 1 — BUILD & CONFIGURE](#phase-1--build--configure)
7. [Phase 1 phụ — Kiến trúc agent](#phase-1-phụ--kiến-trúc-agent)
8. [Phase 1 phụ — UI](#phase-1-phụ--ui)
9. [Phase 1 phụ — Anti-hallucination](#phase-1-phụ--anti-hallucination)
10. [Phase 1 phụ — SSE Streaming](#phase-1-phụ--sse-streaming)
11. [Phase 2 — TEST & DEPLOY](#phase-2--test--deploy)
12. [Phase 3 — OPERATE](#phase-3--operate)
13. [Phase 4 — ADVANCED](#phase-4--advanced)
14. [API endpoints](#api-endpoints)
15. [Checklist nghiệm thu](#checklist-nghiệm-thu)
16. [Xử lý sự cố](#xử-lý-sự-cố)

---

## 1. Mục tiêu và nguyên tắc

### 1.1 Agent làm gì

Agent đọc dữ liệu chiến dịch marketing + hồ sơ vay, tự phân tích và trả lời ba câu hỏi:

1. **Dashboard hiệu quả từng chiến dịch** — chiến dịch nào lãi/lỗ, phễu rơi ở đâu, tiền nên dồn vào đâu
2. **Chân dung tập khách hàng tiềm năng** — ai đáng theo đuổi, bằng chứng nào nói vậy
3. **Hành động nâng cao CLV** — làm gì, với ai, kỳ vọng thu về bao nhiêu

Mọi kết luận truy vết được xuống dòng dữ liệu gốc. Đây là ràng buộc thiết kế số một.

### 1.2 Nguyên tắc nền tảng

```
Code tính toán — LLM chỉ diễn giải.
```

LLM **không bao giờ** tự tính một con số. Mọi con số đến từ SQL đã viết sẵn và kiểm chứng.
LLM nhận một bảng bằng chứng (`EvidenceSet`) và viết văn xuôi quanh nó, với số phát ra
dưới dạng thẻ `{{F1.r1.romi}}`. Thẻ nào không phân giải được về một ô dữ liệu thật thì
câu trả lời bị chặn.

### 1.3 Năm quy tắc không được phá

| # | Quy tắc | Cơ chế ép |
|---|---|---|
| R1 | LLM không bao giờ tự tính một con số | `tests/test_numeric_grounding.py` + lớp L2 |
| R2 | Không nối chuỗi dữ liệu người dùng vào SQL — luôn bind parameter | `tests/test_semantic_compiler.py` |
| R3 | `app/analytics/` và `app/verify/` không import `data`, `llm`, `api`, `memory` | `lint-imports` trong CI |
| R4 | Không hạ ngưỡng kiểm chứng để test xanh — sửa code, đừng sửa rào | `scripts/validate_artifacts.py` |
| R5 | Không hardcode chuỗi hiển thị tiếng Việt trong `.py` — nằm trong YAML | review |

### 1.4 Ba điều về dữ liệu (phải biết trước khi code)

1. **`fact_loan` không có `campaign_id` và không có `lead_id`.** Cầu nối duy nhất tới
   chiến dịch là `sub_channel`. Viết `JOIN ... ON campaign_id` là lỗi kinh điển — cột đó không tồn tại.

2. **1 062/2 687 hồ sơ bị từ chối có `loan_amount`, `tenure`, `rate`, `balance` đều NULL.**
   Đúng về nghiệp vụ. `AVG(loan_amount)` ra đúng, nhưng `SUM(loan_amount)/COUNT(*)` sai 39%.

3. **Lợi nhuận lệch cực mạnh:** trung bình +199 629 VND nhưng trung vị **−86 175 VND**,
   53,8% khách lỗ, top 10% chiếm 81,9% lợi nhuận. Báo cáo trung bình một mình là gây hiểu nhầm.

---

## 2. Skills Index — 9 skill

| Skill | Vai trò | Khi nào invoke |
|---|---|---|
| `/agentbase` | Platform reference — kiến trúc, IAM, "dùng skill nào" | Khi cần hiểu platform |
| `/agentbase-wizard` | Guided 9-step: scaffold → configure → code → test → deploy → verify | **Bắt đầu từ đây** |
| `/agentbase-identity` | Agent identity + outbound auth (API key, OAuth2) cho external services | Khi agent gọi API ngoài |
| `/agentbase-llm` | Platform LLM — API key, model catalog, rate limit, OpenAI-compatible endpoint | Khi cần LLM access |
| `/agentbase-memory` | Conversation history (short-term) + semantic fact extraction (long-term) | Khi agent cần nhớ across sessions |
| `/agentbase-deploy` | Build/push Docker, tạo/cập nhật Custom Agent runtime, OpenClaw, Container Registry | Khi deploy |
| `/agentbase-monitor` | Runtime logs, endpoint logs, CPU/RAM metrics, unified dashboard | Khi vận hành |
| `/agentbase-gateway` | Resource Gateway (MCP) — managed proxy, inbound/outbound auth, policy enforcement | Khi agent dùng MCP tool calling |
| `/agentbase-policy` | Authorization policies — Policy Groups, statements (effect/principal/actions/resources/condition) | Khi cần phân quyền trên gateway |

> `/agentbase-teardown` **KHÔNG dùng** — xóa toàn bộ resource. Nếu cần dọn dẹp, làm thủ công.

---

## 3. Lifecycle Map

```
┌──────────────────────────────────────────────────────────────┐
│ GET STARTED                                                  │
│   /agentbase-wizard ────── guided A → Z                       │
│   /agentbase ───────────── platform reference                 │
├──────────────────────────────────────────────────────────────┤
│ BUILD & CONFIGURE                                            │
│   /agentbase-wizard init ── scaffold project                  │
│   /agentbase-llm ────────── platform LLM access               │
│   /agentbase-identity ───── identities & external auth        │
│   /agentbase-memory ─────── memory stores                     │
├──────────────────────────────────────────────────────────────┤
│ TEST & DEPLOY                                                │
│   /agentbase-wizard test ── validate / local / docker         │
│   /agentbase-deploy ─────── build, push, deploy               │
├──────────────────────────────────────────────────────────────┤
│ OPERATE                                                      │
│   /agentbase-monitor ────── logs, metrics, dashboard          │
│   /agentbase-gateway ────── Resource Gateway (MCP)            │
│   /agentbase-policy ─────── access policies                   │
├──────────────────────────────────────────────────────────────┤
│ ADVANCED                                                     │
│   /agentbase-deploy cr ──── Container Registry                │
│   (KHÔNG dùng /agentbase-teardown)                            │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. Cấu hình cố định (IAM + DB + LLM)

> Cả local và production (sau khi deploy lên GreenNode) đều dùng chung.
> IAM credentials dùng cho **local development** và **gọi platform management APIs**
> (tạo runtime, quản lý identity, memory, gateway, policy). Khi deploy lên Runtime,
> platform **tự tiêm** IAM credentials vào container — không cần đặt tay.

### 4.0 IAM — GreenNode Service Account

| Thông số | Giá trị |
|---|---|
| IAM Client ID | `cc69d86b-d8ea-4ab4-8e12-539563b470c1` |
| IAM Client Secret | `7cac3d7e-1c8e-4413-a8d6-a1cbf0d5b98c` |

**Mục đích:**
- Lấy bearer token để gọi mọi AgentBase API (Identity, Runtime, Memory, Gateway, Policy, CR)
- Đăng nhập Container Registry (`cr.sh credentials docker-login`)
- SDK fallback khi không có env vars

**Cách thiết lập — 3 phương án (chọn một):**

**Phương án A — Environment variables (ưu tiên cao nhất):**
```bash
# macOS/Linux
export GREENNODE_CLIENT_ID="cc69d86b-d8ea-4ab4-8e12-539563b470c1"
export GREENNODE_CLIENT_SECRET="7cac3d7e-1c8e-4413-a8d6-a1cbf0d5b98c"

# Windows PowerShell
$env:GREENNODE_CLIENT_ID = "cc69d86b-d8ea-4ab4-8e12-539563b470c1"
$env:GREENNODE_CLIENT_SECRET = "7cac3d7e-1c8e-4413-a8d6-a1cbf0d5b98c"
```

**Phương án B — `.greennode.json` (fallback, SDK đọc tự động):**
```json
{
  "client_id": "cc69d86b-d8ea-4ab4-8e12-539563b470c1",
  "client_secret": "7cac3d7e-1c8e-4413-a8d6-a1cbf0d5b98c"
}
```

**Phương án C — Shell profile (persistent across sessions):**
```bash
# Thêm vào ~/.bashrc (Linux) hoặc ~/.zshrc (macOS)
echo 'export GREENNODE_CLIENT_ID="cc69d86b-d8ea-4ab4-8e12-539563b470c1"' >> ~/.bashrc
echo 'export GREENNODE_CLIENT_SECRET="7cac3d7e-1c8e-4413-a8d6-a1cbf0d5b98c"' >> ~/.bashrc
source ~/.bashrc
```

**Verify token hoạt động:**
```bash
TOKEN=$(bash .claude/skills/agentbase/scripts/get_token.sh)
echo $TOKEN   # JWT bearer token, có exp claim
# Khi 401 → re-run: bash .claude/skills/agentbase/scripts/get_token.sh --force
```

> **Lưu ý quan trọng:**
> - IAM credentials (`client_id`, `client_secret`) đi vào **env vars** hoặc `.greennode.json`.
> - LLM config (`LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`) đi vào `.env`.
> - Hai thứ này **tách biệt** — IAM authenticate với platform APIs, `.env` giữ app-level config.
> - **KHÔNG bao giờ commit `.greennode.json` hay `.env`** — chỉ `.env.example` được track.
> - Khi deploy lên Runtime, platform tự tiêm `GREENNODE_CLIENT_ID` + `GREENNODE_CLIENT_SECRET`
>   + `GREENNODE_AGENT_IDENTITY` + `GREENNODE_ENDPOINT_URL` — **không đặt tay**, đặt tay sẽ ghi đè.

### 4.1 Database — PostgreSQL trên GreenNode

| Thông số | Giá trị |
|---|---|
| Instance Name | `mkt-insight-db` |
| Host | `49.213.71.93` |
| Port | `5432` |
| User | `master` (master user) |
| Password | `Bank1997` |
| Database name | `mkt_insight` |

**Connection string (SQLAlchemy format):**
```
postgresql+psycopg://master:Bank1997@49.213.71.93:5432/mkt_insight
```

> **Khuyến nghị bảo mật:** User `master` là master user — có full quyền. Trong production
> nên tạo role chỉ đọc (`mkt_agent_ro`) và dùng role đó cho agent. Tuy nhiên, với PoC
> có thể dùng `master` trực tiếp. Nếu tạo role chỉ đọc:
> ```sql
> CREATE ROLE mkt_agent_ro LOGIN PASSWORD '<strong-password>' NOSUPERUSER NOCREATEDB NOCREATEROLE;
> GRANT CONNECT ON DATABASE mkt_insight TO mkt_agent_ro;
> GRANT USAGE ON SCHEMA public, raw, mart, ops TO mkt_agent_ro;
> GRANT SELECT ON ALL TABLES IN SCHEMA public, raw, mart, ops TO mkt_agent_ro;
> ALTER DEFAULT PRIVILEGES IN SCHEMA public, raw, mart, ops GRANT SELECT ON TABLES TO mkt_agent_ro;
> ```

**Cấu trúc schema trong DB:**
- `raw.*` — dữ liệu gốc (fact_loan, dim_campaign, dim_lead, dim_customer, ...)
- `mart.*` — data marts (campaign_performance, customer_segments, ...)
- `ops.*` — vận hành (agent_trace, answer_cache, stream_buffer, dq_results)

### 4.2 LLM Model — GreenNode MaaS

| Thông số | Giá trị |
|---|---|
| Model Name (display) | Qwen 3.6 Flash |
| Base URL | `https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1` |
| API Key | `vn-FSreCmhk_98fxpw_OWBt-l36d072138b9f4aabae0bf27857709f8361FBX69ZDi8jz_Js3bnIxZ-0001bf8578671ea0` |

> **Lưu ý về model identifier:** "Qwen 3.6 Flash" là tên hiển thị. Khi gọi API,
> phải dùng field `path` (hoặc `code` nếu `path` thiếu) từ `aip.sh models list`.
> Trước khi code, chạy:
> ```bash
> bash .claude/skills/agentbase/scripts/aip.sh models list --status ENABLED
> ```
> Tìm model có tên chứa "Qwen" và "Flash", lấy field `path` làm `LLM_MODEL`.

> **Trần rate limit:** MaaS giới hạn **10 request/phút cho cả tài khoản**.
> Kiến trúc phải tiết kiệm: ≤ 2 lượt gọi LLM cho một câu hỏi chat, **0 lượt cho dashboard**.

### 4.3 Tóm tắt `.env`

```bash
# .env — KHÔNG commit file này (chỉ .env.example được track)

# --- Database (dùng chung local + prod) ---
MKT_DATABASE__URL=postgresql+psycopg://master:Bank1997@49.213.71.93:5432/mkt_insight

# --- LLM (dùng chung local + prod) ---
LLM_API_KEY=vn-FSreCmhk_98fxpw_OWBt-l36d072138b9f4aabae0bf27857709f8361FBX69ZDi8jz_Js3bnIxZ-0001bf8578671ea0
LLM_BASE_URL=https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1
LLM_MODEL=<model-path-từ-aip.sh-models-list>
LLM_JUDGE_MODEL=<model-path-từ-aip.sh-models-list>   # có thể dùng cùng model

# --- Memory (sau Step 3) ---
MEMORY_ID=<memory-id-từ-agentbase-memory>
MEMORY_STRATEGY_ID=default

# --- App ---
APP_PROFILE=local                # local | greennode | test
LOG_LEVEL=info
MKT_ADMIN__TOKEN=<random-string> # bảo vệ /api/admin/*
```

> **IAM credentials KHÔNG nằm trong `.env`.** Chúng đi vào environment variables
> hoặc `.greennode.json` (xem §4.0). Lý do: IAM authenticate với platform APIs,
> còn `.env` giữ app-level config. SDK kiểm tra theo thứ tự ưu tiên:
> env vars > `.greennode.json` > defaults.
>
> **Khi deploy lên Runtime:** platform tự tiêm 4 biến sau — KHÔNG đặt trong `.env` deploy:
> - `GREENNODE_CLIENT_ID` (auto-injected)
> - `GREENNODE_CLIENT_SECRET` (auto-injected)
> - `GREENNODE_AGENT_IDENTITY` (auto-injected)
> - `GREENNODE_ENDPOINT_URL` (auto-injected)

---

## Phase 0 — GET STARTED

### 0.1 Cài đặt bộ skill

```bash
# Claude Code
claude plugin marketplace add vngcloud/greennode-agentbase-skills
# Trong Claude Code:
/plugin install greennode-agentbase@greennode-agentbase
```

Hoặc clone repo và đặt `skills/` vào `.claude/skills/`:

```bash
git clone https://github.com/vngcloud/greennode-agentbase-skills.git
cp -r greennode-agentbase-skills/skills/ .claude/skills/
```

### 0.2 IAM credentials (bắt buộc trước mọi thao tác platform)

> Credentials đã có sẵn — xem [§4.0](#40-iam--greennode-service-account) cho giá trị đầy đủ.

IAM Service Account đã tạo và attach policies (`AgentBaseFullAccess`, `vcrFullAccess`,
`AiPlatformFullAccess`). Thiết lập credentials (chọn một phương án):

```bash
# Phương án A — Environment variables (ưu tiên)
# macOS/Linux
export GREENNODE_CLIENT_ID="cc69d86b-d8ea-4ab4-8e12-539563b470c1"
export GREENNODE_CLIENT_SECRET="7cac3d7e-1c8e-4413-a8d6-a1cbf0d5b98c"

# Windows PowerShell
$env:GREENNODE_CLIENT_ID = "cc69d86b-d8ea-4ab4-8e12-539563b470c1"
$env:GREENNODE_CLIENT_SECRET = "7cac3d7e-1c8e-4413-a8d6-a1cbf0d5b98c"
```

```json
// Phương án B — .greennode.json (fallback)
{
  "client_id": "cc69d86b-d8ea-4ab4-8e12-539563b470c1",
  "client_secret": "7cac3d7e-1c8e-4413-a8d6-a1cbf0d5b98c"
}
```

Verify:
```bash
TOKEN=$(bash .claude/skills/agentbase/scripts/get_token.sh)
# → JWT bearer token. Khi 401: re-run với --force
```

> **KHÔNG bao giờ commit `.greennode.json` hay `.env`** — chỉ `.env.example` được track.
> Khi deploy lên Runtime, platform tự tiêm IAM credentials — không cần đặt trong `.env` deploy.

### 0.3 Khởi động wizard

```
/agentbase-wizard
```

Wizard chạy 9 bước. Các bước 3 (Memory) và 4 (Identity) là optional nhưng
agent mới **sẽ làm cả hai**.

---

## Phase 1 — BUILD & CONFIGURE

### Step 1/9: Kiểm tra prerequisites

```bash
bash .claude/skills/agentbase/scripts/check_credentials.sh iam
TOKEN=$(bash .claude/skills/agentbase/scripts/get_token.sh)
```

Nếu credentials thiếu → làm §0.2 trước. Token cache trong `.agentbase/token_cache`,
tự validate qua JWT `exp`. Khi 401 → re-run với `--force`.

### Step 2/9: Scaffold project

```
/agentbase-wizard init mkt-insight-agent-v2 --langgraph
```

> **Framework:** Chọn **LangGraph + Memory** (`--langgraph-memory`) để có
> `AgentBaseMemoryEvents` checkpointer + `MemoryClient` SDK. Luồng agent chính
> là máy trạng thái tuyến tính — LangGraph chỉ dùng cho memory integration.
> Nếu muốn đơn giản hơn, chọn **Custom** và tích hợp `MemoryClient` trực tiếp.

#### Cấu trúc project hoàn chỉnh

```
mkt-insight-agent-v2/
├── main.py                      # Entrypoint — GreenNodeAgentBaseApp + FastAPI mount
├── Dockerfile                   # python:3.13-slim, EXPOSE 8080
├── requirements.txt             # greennode-agentbase + deps
├── .greennode.json              # SDK config (client_id, client_secret, agent_identity)
├── .env.example                 # template — KHÔNG commit .env
├── .env                         # credentials thật — KHÔNG commit
├── .gitignore
├── .dockerignore
├── app/
│   ├── __init__.py
│   ├── contracts.py             # Protocol + type definitions (EvidenceSet, Fact, TrustScore, ...)
│   ├── errors.py                # Error tree (40 mã lỗi)
│   ├── settings.py              # pydantic-settings (env-driven config)
│   ├── logging_.py              # structured logging
│   ├── agent/                   # Orchestrator + luồng agent
│   │   ├── __init__.py
│   │   ├── orchestrator.py      # answer() + answer_stream() — điều phối toàn luồng
│   │   ├── router.py            # LLM/regex → Intent + Entities
│   │   ├── planner.py           # Playbook + entities → PlannedSection[]
│   │   ├── playbooks.py         # Playbook definitions (từ config YAML)
│   │   ├── narrator.py          # EvidenceSet → prompt → LLM stream tokens
│   │   ├── renderer.py          # Thay thẻ → số, định dạng vi-VN
│   │   ├── stages.py            # Thông báo tiến trình (từ config/stages.yaml)
│   │   ├── streaming.py         # StreamingVerifier — kiểm chứng theo khối
│   │   └── tools/               # Tool calling (MCP, memory, export)
│   ├── analytics/               # Toán học thuần túy — KHÔNG I/O
│   │   ├── __init__.py
│   │   ├── clv.py               # Customer Lifetime Value
│   │   ├── segments.py          # Phân khúc khách hàng
│   │   ├── stats.py             # z-test, bootstrap, Wilson CI
│   │   └── actions.py           # Khuyến nghị D3
│   ├── api/                     # FastAPI routes
│   │   ├── __init__.py
│   │   ├── server.py            # create_app() — mount tất cả routes
│   │   ├── dashboard.py         # GET /api/dashboard/*
│   │   ├── chat.py              # POST /api/chat (SSE)
│   │   ├── segments.py          # GET /api/segments/*
│   │   ├── actions.py           # GET /api/actions
│   │   ├── admin.py             # /api/admin/* (prompt, metrics, quality, etl)
│   │   └── invocations.py       # POST /invocations (non-streaming)
│   ├── data/                    # DB access — sở hữu kết nối
│   │   ├── __init__.py
│   │   ├── db.py                # 3 pool tách biệt (ro, trace, admin)
│   │   ├── sqlguard.py          # L0: SQL AST check (sqlglot)
│   │   └── catalog.py           # Dimension value cache
│   ├── llm/                     # LLM client — OpenAI-compatible
│   │   ├── __init__.py
│   │   ├── client.py            # OpenAI SDK wrapper + retry/backoff/rate-limit
│   │   └── rate_limiter.py      # Token bucket 8 req/phút
│   ├── memory/                  # MỚI: Memory service wrapper
│   │   ├── __init__.py
│   │   ├── client.py            # MemoryClient wrapper
│   │   └── tools.py             # remember/recall tools
│   ├── prompts/                 # Prompt loader + renderer
│   │   ├── __init__.py
│   │   └── loader.py            # Nap YAML prompt, hot-reload, version
│   ├── semantic/                # Semantic layer — sở hữu định nghĩa chỉ số
│   │   ├── __init__.py
│   │   ├── compiler.py          # MetricRequest → SQL (bind param, KHÔNG nối chuỗi)
│   │   ├── metrics.py           # Nap config/semantic/metrics.yml
│   │   └── entities.py          # Nap config/semantic/entities.yml
│   ├── verify/                  # 7+1 lớp chống hallucination — thuần hàm
│   │   ├── __init__.py
│   │   ├── numeric.py           # L2: Numeric grounding (PCN)
│   │   ├── entity.py            # L3: Entity grounding
│   │   ├── stats_guard.py       # L4: Stats guard + skew guard
│   │   ├── judge.py             # L5: LLM judge (async)
│   │   ├── consistency.py       # Self-consistency (freeform only)
│   │   ├── pipeline.py          # L6: Trust Score + decision
│   │   ├── config.py            # Nap config/verify.yaml
│   │   ├── models.py            # CheckResult, TrustScore, Band, Severity
│   │   └── vi_text.py           # Trích tên riêng tiếng Việt
│   ├── web/                     # UI
│   │   ├── __init__.py
│   │   ├── formatting.py        # fmt_vnd, fmt_pct, fmt_ratio (vi-VN)
│   │   ├── templates/
│   │   │   ├── base.html        # Layout chung: header + Tailwind + Alpine + ECharts CDN
│   │   │   ├── index.html       # Trang chính: dashboard + chat
│   │   │   ├── _dashboard.html  # Tab D1: KPI + charts + bảng
│   │   │   ├── _persona.html    # Tab D2: phân khúc
│   │   │   ├── _actions.html    # Tab D3: khuyến nghị
│   │   │   ├── _chat.html       # Tab Hỏi đáp: chat + composer
│   │   │   ├── _kpi.html        # KPI card partial
│   │   │   ├── _evidence_panel.html  # "Xem SQL & dữ liệu" panel
│   │   │   └── admin/           # Trang admin (sửa prompt, metric, quality)
│   │   └── static/
│   │       ├── app.js           # Alpine.js app state + tab switching
│   │       ├── chat.js          # SSE client + message rendering
│   │       ├── charts.js        # ECharts init (bar, funnel, waterfall, line, scatter, treemap)
│   │       ├── format.js        # Intl.NumberFormat('vi-VN') — đối chiếu backend
│   │       ├── styles.css       # Custom styles + 60vh constraint
│   │       └── admin.js         # Admin page JS
│   └── telemetry/
│       ├── __init__.py
│       └── trace.py             # Ghi ops.agent_trace
├── config/                      # YAML configs (KHÔNG hardcode trong .py)
│   ├── app.yaml                 # App-level config
│   ├── analytics.yaml           # 8 luật phân khúc, p_repeat, 6 hành động D3
│   ├── verify.yaml              # Ngưỡng 7 lớp chống hallucination
│   ├── stages.yaml              # Thông báo tiến trình streaming
│   ├── semantic/
│   │   ├── metrics.yml          # 53 chỉ số, 42 có giá trị đối chứng (reference)
│   │   └── entities.yml         # 4 dataset, 25 dimension
│   ├── playbooks/
│   │   ├── campaign_overview.yml
│   │   ├── campaign_diagnosis.yml
│   │   ├── funnel_analysis.yml
│   │   ├── customer_persona.yml
│   │   ├── segment_deep_dive.yml
│   │   ├── clv_actions.yml
│   │   ├── risk_fraud.yml
│   │   ├── data_question.yml
│   │   └── freeform.yml
│   ├── profiles/
│   │   ├── local.yaml
│   │   ├── greennode.yaml
│   │   └── test.yaml
│   └── secrets.example.yaml     # Template (secrets.yaml KHÔNG commit)
├── prompts/                     # Prompt YAML files
│   ├── narrate_campaign.yaml
│   ├── narrate_persona.yaml
│   ├── narrate_actions.yaml
│   ├── judge_grounding.yaml
│   ├── route_intent.yaml
│   └── ...
├── etl/                         # ETL pipelines
│   ├── __init__.py
│   ├── load_excel.py            # Nap data/*.xlsx → raw.*
│   ├── build_marts.py           # raw.* → mart.*
│   ├── dq_checks.py             # Data quality checks (12 bất biến)
│   └── sql/
│       ├── ddl.sql              # Schema DDL
│       └── ...
├── evals/                       # Golden set + eval runner
│   ├── __init__.py
│   ├── run_eval.py
│   └── golden/
│       └── qa_set.yaml          # 100 ca golden, 37 ca bẫy
├── scripts/
│   ├── validate_artifacts.py    # Nhất quán cấu hình
│   ├── verify_metrics_duckdb.py # Đối chiếu chỉ số với dữ liệu thật
│   └── deploy.ps1               # One-command deploy
├── tests/                       # pytest test suite
│   ├── test_numeric_grounding.py
│   ├── test_semantic_compiler.py
│   ├── test_streaming.py
│   └── ...
└── data/                        # Dữ liệu gốc (KHÔNG copy vào Docker image)
    ├── full_schema_mock_v2.xlsx
    └── parquet/
```

#### `main.py` — entrypoint

```python
import os
from greennode_agentbase import GreenNodeAgentBaseApp, RequestContext, PingStatus
from dotenv import load_dotenv

load_dotenv()

app = GreenNodeAgentBaseApp()

# FastAPI app mount BÊN TRONG SDK — phục vụ dashboard + SSE chat + admin
from app.api.server import create_app
fastapi_app = create_app()
app.mount("/", fastapi_app)


@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    """POST /invocations — cổng non-streaming cho Zalo/API ngoài."""
    from app.agent.orchestrator import Orchestrator
    orch = Orchestrator.from_env()
    result = orch.answer(
        payload.get("message", ""),
        history=payload.get("history", []),
        user_id=context.user_id,
        session_id=context.session_id,
    )
    return result.to_invocation_response()


@app.ping
def health_check() -> PingStatus:
    """GET /health — chỉ kiểm tra process sống, KHÔNG chạm DB."""
    return PingStatus.HEALTHY


if __name__ == "__main__":
    app.run(port=8080, host="0.0.0.0")
```

> **Runtime contract (HARD):**
> 1. Lắng nghe `0.0.0.0:8080`
> 2. `GET /health` trả 200
>
> `/health` chỉ khẳng định process còn sống. `/readyz` mới nói có phục vụ được
> hay không (DB nối được, DQ không có lỗi BLOCK, catalog nạp xong). Tách rời
> để runtime không bị kill khi DB tạm mất.

#### `Dockerfile`

```dockerfile
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      libpq5 curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py       ./
COPY app/          ./app/
COPY prompts/      ./prompts/
COPY config/       ./config/
COPY etl/          ./etl/

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/health || exit 1

CMD ["python", "main.py"]
```

Không COPY `data/`, `docs/`, `tests/`, `evals/` — dữ liệu nằm trong PostgreSQL.

#### `requirements.txt`

```
# --- AgentBase SDK ---
greennode-agentbase
greennode-agent-bridge[langgraph]

# --- Web ---
fastapi
uvicorn[standard]
jinja2
sse-starlette

# --- LLM ---
openai
python-dotenv

# --- Database ---
sqlalchemy>=2.0
psycopg[binary]

# --- Analytics ---
scipy
statsmodels

# --- SQL parsing (L0) ---
sqlglot

# --- Config ---
pydantic-settings
pyyaml

# --- Caching ---
cachetools
```

#### `.env.example`

```bash
# .env.example — template, commit được. Copy sang .env và điền giá trị thật.
# IAM credentials KHÔNG nằm đây — xem .greennode.json hoặc env vars (§4.0).

# --- Database (dùng chung local + prod) ---
MKT_DATABASE__URL=postgresql+psycopg://master:Bank1997@49.213.71.93:5432/mkt_insight

# --- LLM ---
LLM_API_KEY=vn-FSreCmhk_98fxpw_OWBt-l36d072138b9f4aabae0bf27857709f8361FBX69ZDi8jz_Js3bnIxZ-0001bf8578671ea0
LLM_BASE_URL=https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1
LLM_MODEL=
LLM_JUDGE_MODEL=

# --- Memory ---
MEMORY_ID=
MEMORY_STRATEGY_ID=default

# --- App ---
APP_PROFILE=local
LOG_LEVEL=info
MKT_ADMIN__TOKEN=
```

#### `.greennode.json`

```json
{
  "client_id": "cc69d86b-d8ea-4ab4-8e12-539563b470c1",
  "client_secret": "7cac3d7e-1c8e-4413-a8d6-a1cbf0d5b98c",
  "agent_identity": ""
}
```

> `client_id` + `client_secret` đã điền sẵn từ IAM Service Account (§4.0).
> `agent_identity` điền sau Step 4 (tạo identity qua `/agentbase-identity`).
> File này **KHÔNG commit** (đã có trong `.gitignore`).

#### `.gitignore`

```
__pycache__/
*.py[cod]
.env
.env.*
!.env.example
.greennode.json
config/secrets.yaml
.agentbase/
.agentbase-state.json
*.credentials.json
.venv/
venv/
*.egg-info/
dist/
build/
data/
```

#### `.dockerignore`

```
.venv/
venv/
__pycache__/
*.py[cod]
.env
.env.*
.greennode.json
.agentbase/
.agentbase-state.json
*.credentials.json
.git/
.gitignore
*.md
data/
docs/
tests/
evals/
```

### Step 3/9: Set Up Memory

```
/agentbase-memory memory create
```

Tham số:
- **name**: `mkt-insight-v2-memory`
- **description**: "Conversation history + semantic facts for Marketing Insight Agent v2"
- **eventExpiryDuration**: 30 (ngày)
- **Strategy**: `SEMANTIC`
- **enableAutomaticMemoryRecordGeneration**: `true`

Lưu `memory_id`:
```bash
bash .claude/skills/agentbase/scripts/save_env_var.sh --key MEMORY_ID --value <memory-id>
```

#### Tích hợp vào code

**Short-term memory (conversation history):**

```python
# app/agent/orchestrator.py
from greennode_agent_bridge import AgentBaseMemoryEvents

checkpointer = AgentBaseMemoryEvents(
    memory_id=os.environ["MEMORY_ID"],
)
# builder.compile(checkpointer=checkpointer)  # LangGraph
```

**Long-term memory (semantic facts):**

```python
# app/memory/tools.py
from greennode_agentbase import MemoryClient

memory_client = MemoryClient.from_env()

async def remember(fact: str, actor_id: str) -> str:
    await memory_client.insert_memory_record_directly(
        memory_id=os.environ["MEMORY_ID"],
        actor_id=actor_id,
        content=fact,
    )
    return "Đã ghi nhớ."

async def recall(query: str, actor_id: str) -> str:
    results = await memory_client.search_memory_records(
        memory_id=os.environ["MEMORY_ID"],
        actor_id=actor_id,
        query=query,
        limit=5,
    )
    return "\n".join(r.content for r in results)
```

#### Headers bắt buộc khi dùng memory

```
X-GreenNode-AgentBase-User-Id: <user-id>       # maps to actor_id
X-GreenNode-AgentBase-Session-Id: <session-id>  # conversation thread
```

UI phải gửi kèm hai header này khi gọi `/api/chat`.

> **Tương tác với anti-hallucination:** Long-term memory facts phải qua L3 entity
> grounding trước khi dùng. Fact từ memory không tự động "trusted".

### Step 4/9: Set Up Identity & External Auth

```
/agentbase-identity identity create --name mkt-insight-v2-identity
```

Update `.greennode.json` với `agent_identity`.

#### Lưu DB credentials qua Identity (thay vì hardcode trong `.env`)

```bash
/agentbase-identity auth apikey create \
  --provider-name db-readonly \
  --apikey-file .secrets/db-password.key
```

Tại runtime:
```python
from greennode_agentbase import requires_api_key

@app.entrypoint
@requires_api_key(provider_name="db-readonly")
def handler(payload, context, api_key: str):
    # api_key injected tự động từ Identity service
    ...
```

> **Lợi ích:** Secrets nằm trên platform, xoay credential không cần redeploy.

### Step 5/9: Customize Agent Code

Viết code nghiệp vụ theo kiến trúc ở [Phase 1 phụ — Kiến trúc agent](#phase-1-phụ--kiến-trúc-agent).

### Step 6/9: Configure Environment

```bash
bash .claude/skills/agentbase/scripts/check_env.sh .
```

Đảm bảo `.env` có đầy đủ giá trị từ §4.3. Verify:
```bash
bash .claude/skills/agentbase/scripts/check_credentials.sh llm
```

---

## Phase 1 phụ — Kiến trúc agent

### Luồng xử lý end-to-end

```
Người dùng đặt câu hỏi
    │
    ▼
┌─ ROUTE (router.py) ──────────────────────────────┐
│  LLM hoặc regex → Intent + Entities              │
│  OUT_OF_SCOPE → từ chối qua prompt              │
│  (cache theo chuẩn hoá câu hỏi)                  │
└──────────────────────────────────────────────────┘
    │
    ▼
┌─ RECALL (memory/tools.py) ───────────────────────┐
│  Tìm long-term facts liên quan từ Memory service  │
│  Facts → qua L3 entity grounding trước khi dùng   │
└──────────────────────────────────────────────────┘
    │
    ▼
┌─ PLAN (planner.py) ──────────────────────────────┐
│  Playbook + entities → PlannedSection[]           │
│  Mỗi section → MetricRequest (chỉ số + filter)    │
│  Danh sách chỉ số cố định trong YAML — KHÔNG do   │
│  LLM tự chọn (tiết kiệm 1-2 lượt gọi)             │
└──────────────────────────────────────────────────┘
    │
    ▼
┌─ COMPUTE (orchestrator.py::_build_evidence) ─────┐
│  MetricRequest → SQL (bind param) → DB → Fact    │
│  Nhiều Fact → EvidenceSet                         │
│  + Comparisons (kiểm định thống kê)               │
│  + Actions (từ config, không do LLM)              │
│                                                   │
│  SSE: event/table (fact_id, columns, rows, sql)   │
│  SSE: event/chart (playbook.charts config)        │
└──────────────────────────────────────────────────┘
    │
    ▼
┌─ NARRATE (narrator.py) ──────────────────────────┐
│  EvidenceSet → prompt → LLM stream tokens         │
│  Fact_id list + reminder chèn TRƯỚC evidence      │
│  trong user message (giúp model tuân thủ)         │
│  LLM chỉ viết CHỮ, KHÔNG viết SỐ                  │
│  Số phát ra dưới dạng thẻ: {{F1.r1.romi}}         │
└──────────────────────────────────────────────────┘
    │
    ▼
┌─ STREAMING VERIFIER (streaming.py) ──────────────┐
│  Token → buffer → cut tại ranh giới markdown      │
│  → _repair_tags() → substitute → L2 + L3          │
│  → emit block (verified=true/false)               │
│                                                   │
│  SSE: event/block (md, verified, numbers)         │
└──────────────────────────────────────────────────┘
    │
    ▼
┌─ VERIFY (pipeline.py) ───────────────────────────┐
│  Toàn bộ narrative → L2 + L3 + L4                 │
│  → TrustScore (band: PASS/HEDGE/ABSTAIN/BLOCK)    │
│                                                   │
│  SSE: event/verified (trust, band, checks)        │
└──────────────────────────────────────────────────┘
    │
    ▼
┌─ REMEMBER (memory/tools.py) ─────────────────────┐
│  Lưu câu hỏi + câu trả lời vào short-term memory  │
│  (qua checkpointer — tự động)                     │
│  Nếu phát hiện fact mới → lưu long-term (optional)│
└──────────────────────────────────────────────────┘
    │
    ▼
┌─ DONE + JUDGE (async) ───────────────────────────┐
│  SSE: event/done (trace_id, decision, latency)    │
│  L5 judge chạy nền → SSE: event/judge             │
│  → ghi ops.agent_trace                            │
└──────────────────────────────────────────────────┘
```

### Ranh giới module

```
app/api        -> chỉ biết HTTP. Không có logic nghiệp vụ.
app/agent      -> dàn đặt luồng. Không viết SQL, không gọi DB trực tiếp.
app/semantic   -> sở hữu định nghĩa chỉ số. Sinh SQL. Không gọi LLM.
app/data       -> sở hữu kết nối. Thực thi SQL. Không biết gì về chỉ số.
app/analytics  -> toán học thuần túy (CLV, phân khúc, thống kê). Không I/O.
app/verify     -> nhận (answer, evidence) -> trả về kết quả kiểm tra. Thuần ham.
app/llm        -> gọi model. Không biết gì về nghiệp vụ.
app/prompts    -> nap và render prompt. Không gọi model.
app/memory     -> MemoryClient wrapper. Không biết nghiệp vụ.
```

Quy tắc phụ thuộc (kiểm tra bằng `lint-imports`):
- `analytics` và `verify` **không được import** `data`, `llm`, `api`, `memory`
- `semantic` không được import `llm`
- Chỉ `agent` được phép điều phối nhiều module

### Ngân sách LLM (trần 10 RPM)

| Quyết định | Tiết kiệm |
|---|---|
| Dashboard hoàn toàn không gọi LLM (SQL + template) | 0 gọi cho màn hình hay dùng nhất |
| Playbook thay vì để LLM lập kế hoạch tự do | Bỏ 1-2 lượt "suy nghĩ" |
| Router và Narrator gộp khi có thể | −1 lượt |
| LLM-judge chạy bất đồng bộ, không chặn | Người dùng không phải chờ |
| Cache theo hash(câu hỏi + prompt version + data version) | Câu hỏi lặp tốn 0 lượt |
| Token bucket phía client, 8 req/phút | Không bao giờ 429 |

Mục tiêu: **≤ 2 lượt gọi LLM cho chat, 0 lượt cho dashboard**.

---

## Phase 1 phụ — UI

### Tech stack

| Lớp | Lựa chọn | Lý do |
|---|---|---|
| Web | **FastAPI** + Uvicorn | Async, SSE, tự sinh OpenAPI |
| Template | Jinja2 | Có sẵn trong FastAPI, không cần build JS |
| CSS | **Tailwind CSS** (CDN play script) | Ràng buộc chat 60% viết bằng một class |
| JS tương tác | **Alpine.js** (CDN) | ~15 KB, đủ tab/state/stream; không cần bundler |
| Biểu đồ | **Apache ECharts** (CDN) | Mạnh cho funnel, waterfall, scatter |
| Markdown | `marked` (CDN) + **DOMPurify** (CDN) | Render + sanitize XSS |

### Bố cục giao diện

```
+======================================================================+
| Marketing Insight Agent    [Dữ liệu: 01-31/08/2026]  [ETL: 2h trước] |  56px
+======================================================================+
|                                                                      |
|  +----------------+ +----------------+ +----------------+            |
|  | KPI 1          | | KPI 2          | | KPI 3          |            |  KPI cards
|  +----------------+ +----------------+ +----------------+            |
|                                                                      |
|  +--------------------------------+ +-----------------------------+  |
|  | Chart 1 (bar, âm/dương tô màu) | | Chart 2 (funnel)            |  |  DASHBOARD
|  +--------------------------------+ +-----------------------------+  |  (cuộn)
|                                                                      |
|  +------------------------------------------------------------+     |
|  | Bảng chi tiết (sortable)                                    |     |
|  +------------------------------------------------------------+     |
+======================================================================+
|  [Chiến dịch] [Chân dung KH] [Hành động CLV] [Hỏi đáp]   <- tab      |
+======================================================================+
|  VÙNG HỘI THOẠI  -- max-height: 60vh, cuộn riêng                    |
|                                                                      |
|   User: <câu hỏi>                                                    |
|                                                                      |
|   Agent: ### Kết luận                                                |
|          <nội dung>...                                               |  <= 60vh
|          [🟢 Đã kiểm chứng  12/12 số khớp]  [Xem SQL & dữ liệu]     |
|                                                                      |
+----------------------------------------------------------------------+
|  [ Nhập câu hỏi...                                  ]  [Gửi]        |  composer
+======================================================================+
```

### Ràng buộc 60% (phải giữ)

```css
#chat-scroll { max-height: 60vh; }
@supports (height: 100dvh) { #chat-scroll { max-height: 60dvh; } }
@media (max-width: 768px) { #chat-scroll { max-height: 55dvh; } }
```

Ba điểm phải làm đúng:
1. `max-height` chứ không phải `height` — hội thoại ngắn thì khung co lại
2. `60vh` áp cho đúng vùng cuộn, không tính tab và composer
3. Mobile dùng `dvh` thay vì `vh` (iOS Safari thanh địa chỉ co giãn)

```html
<div id="chat-scroll"
     class="overflow-y-auto overscroll-contain"
     style="max-height: 60vh;">
  <template x-for="m in messages"> ... </template>
</div>
<form class="border-t p-3 flex gap-2" @submit.prevent="send()">
  <input class="flex-1 rounded-lg border px-3 py-2" x-model="draft">
  <button class="rounded-lg px-4 py-2 bg-slate-900 text-white">Gửi</button>
</form>
```

### Bốn tab

| Tab | Nội dung | Gọi LLM |
|---|---|---|
| **Chiến dịch** (D1) | KPI, ROMI bar chart (âm tô đỏ), phễu, xu hướng, bảng chi tiết | **0** |
| **Chân dung KH** (D2) | Thẻ phân khúc: size, CLV kèm khoảng, repeat rate kèm CI | **0** |
| **Hành động CLV** (D3) | Khuyến nghị: phân khúc, tác động, nút xuất CSV | **0** |
| **Hỏi đáp** | Chat tự do, SSE streaming | ≤ 2 |

> Ba tab đầu **không gọi LLM** — dữ liệu từ SQL, phần chữ từ template điền số.

### Trust badge + Evidence panel

```
+------------------------------------------------------------+
| ### Kết luận                                               |
| <nội dung câu trả lời>                                     |
|                                                            |
| [🟢 Đã kiểm chứng]  12/12 số khớp  |  [Xem SQL & dữ liệu]  |
+------------------------------------------------------------+
```

Bấm "Xem SQL & dữ liệu" mở panel:
- SQL đã chạy
- Bảng kết quả (columns + rows)
- Kết quả từng lớp kiểm tra (L2, L3, L4, L5)
- Caveats

Màu huy hiệu: 🟢 PASS · 🟡 HEDGE · ⚪ ABSTAIN · 🔴 BLOCKED

### Soft-block UI (khối không qua kiểm chứng)

```html
<!-- verified=true: bg slate-100 -->
<div class="md-content rounded-lg px-3 py-2 bg-slate-100" x-html="p.html"></div>

<!-- verified=false: bg amber-50 + border amber + warning icon -->
<div class="rounded-lg px-3 py-2 bg-amber-50 border border-amber-200">
  <span class="text-amber-600">⚠</span>
  <div class="text-[11px] text-amber-700">Chưa đối chiếu được (<lý do>)</div>
  <div class="md-content text-slate-700" x-html="p.html"></div>
</div>
```

### Biểu đồ (ECharts) — bốn quy tắc

1. **Giá trị âm luôn tô khác màu** — ROMI âm phải bật ra khỏi màn hình
2. **Cỡ mẫu luôn hiện** — mọi tỷ lệ kèm `n` trong tooltip; cột `n < 30` vẽ gạch chéo
3. **Khoảng tin cậy vẽ thành thanh sai số** — không có cột đặc cho `p = 86,2%, n = 29`
4. **Trục tiền tệ rút gọn** (`392,5 tr`) nhưng tooltip hiện đầy đủ (`392.498.500 VND`)

| Biểu đồ | Loại | Dữ liệu |
|---|---|---|
| ROMI theo chiến dịch | bar ngang, âm/dương khác màu | `/api/dashboard/campaigns` |
| Phễu | funnel | lead → hồ sơ → giải ngân |
| Phân rã lợi nhuận | waterfall | doanh thu → chi phí → lợi nhuận ròng |
| Xu hướng theo ngày | line, 31 điểm | `/api/dashboard/trend` |
| Kích thước × giá trị phân khúc | scatter, bán kính = size | `/api/segments` |
| Tỷ lệ vay lại theo nhóm | bar + thanh sai số | `/api/segments` |
| Lý do từ chối | treemap 2 cấp | `reason_level_1` → `reason_level_2` |

### Định dạng số vi-VN (một nguồn duy nhất cho backend + frontend)

```python
# app/web/formatting.py
def fmt_vnd(v: float | None) -> str:
    if v is None: return "—"
    return f"{v:,.0f}".replace(",", ".") + " VND"      # 392.498.500 VND

def fmt_vnd_short(v: float | None) -> str:
    if v is None: return "—"
    a = abs(v)
    if a >= 1e9: return f"{v/1e9:,.1f}".replace(".", ",") + " tỷ"
    if a >= 1e6: return f"{v/1e6:,.1f}".replace(".", ",") + " tr"
    return fmt_vnd(v)

def fmt_pct(v: float | None, d: int = 1) -> str:
    return "—" if v is None else f"{v*100:.{d}f}".replace(".", ",") + "%"

def fmt_ratio(v: float | None, d: int = 2) -> str:
    return "—" if v is None else f"{v:.{d}f}".replace(".", ",")
```

`None` luôn hiển thị `—`, không bao giờ `0`.
Frontend dùng `Intl.NumberFormat('vi-VN')` + test đối chiếu hai bên.

### Markdown rendering + XSS protection

```javascript
function renderMarkdown(md) {
  marked.setOptions({ breaks: true, gfm: true });
  const html = marked.parse(md);
  return DOMPurify.sanitize(html);  // chặn <script>, on*
}
```

DOMPurify chặn XSS — defense-in-depth.

---

## Phase 1 phụ — Anti-hallucination

### Bảy lớp + L7

| Lớp | Bắt lỗi gì | File | Gọi LLM | Độ trễ | Tất định |
|---|---|---|---|---|---|
| **L0** SQL tĩnh (AST) | Bịa bảng/cột, DML, thiếu LIMIT | `app/data/sqlguard.py` | 0 | ~5ms | ✅ |
| **L1** EXPLAIN dry-run | Lỗi kiểu, truy vấn nặng | (freeform only) | 0 | ~20ms | ✅ |
| **L2** Numeric grounding (PCN) | Số bịa, trích sai, lẫn đơn vị | `app/verify/numeric.py` | 0 | ~1ms | ✅ |
| **L3** Entity grounding | Bịa tên chiến dịch/kênh/phân khúc | `app/verify/entity.py` | 0 | ~1ms | ✅ |
| **L4** Stats guard | So sánh trên nhiễu, mẫu nhỏ, suy nhân quả | `app/verify/stats_guard.py` | 0 | ~10ms | ✅ |
| **L5** LLM judge | Suy diễn không cơ sở, lạc đề | `app/verify/judge.py` | 1 (async) | ngoài găng | ❌ |
| **L6** Trust Score + decision | Ra quyết định cuối | `app/verify/pipeline.py` | 0 | ~1ms | ✅ |
| **L7** Policy enforcement | Tool bị deny qua gateway | `app/agent/tools/` | 0 | ~1ms | ✅ |

L0–L1 chỉ cho đường freeform SQL. L7 chỉ khi dùng Resource Gateway.

### L2 — Numeric grounding (PCN): lớp quan trọng nhất

**Proof-Carrying Numbers:** số phát ra dưới dạng thẻ `{{fact_id}}`, verifier
kiểm tra từng thẻ có phân giải về ô dữ liệu thật không.

```python
# app/verify/numeric.py

NUM_RE = re.compile(r"""
    (?<![\w.])                      # không định vào chữ
    -?\d{1,3}(?:[.\s]\d{3})*        # 1.234.567 hoặc 1 234 567 (kiểu vi-VN)
    (?:,\d+)?                       # phần thập phân dấu phẩy
    \s*(?:%|tỷ|triệu|nghìn|VND|đ)?  # đơn vị tiếng Việt
    | -?\d+(?:\.\d+)?%?             # dạng số thuần
""", re.VERBOSE)

ALLOWLIST = {
    "years":     lambda v: 2000 <= v <= 2100 and float(v).is_integer(),
    "ordinals":  lambda v: v in range(1, 11),
    "literals":  lambda v: v in (0, 1, 2, 100),
}

def check_numeric_grounding(text: str, ev: EvidenceSet, cfg) -> CheckResult:
    # 1. Trích tất cả thẻ {{...}} và kiểm tra resolve
    refs = extract_evidence_refs(text)
    unresolved_tags = [ref for ref in refs if ev.resolve(ref) is None]

    # 2. Thay thẻ → số, rồi quét số trần (bare numbers)
    rendered_text, _ = ev.substitute(text)
    bare_numbers = []
    for raw in find_bare_numbers(rendered_text):
        value = parse_vi_number(raw)
        if _is_allowlisted(value, cfg): continue
        if _matches_under_any_policy(value, ev, cfg): continue
        bare_numbers.append(raw)

    # 3. Pass khi không có thẻ unresolved và không có số trần
    passed = not unresolved_tags and not bare_numbers
    total = len(refs) + len(bare_numbers)
    rate = len(refs) / total if total else 1.0
    return CheckResult(
        name="numeric_grounding", passed=passed, score=rate,
        details={"unresolved_tags": unresolved_tags, "bare_numbers": bare_numbers},
        severity=Severity.BLOCK,
    )
```

Chính sách so khớp (`config/verify.yaml`):
```yaml
numeric:
  policy:
    default:  {mode: round,   decimals: 2}
    vnd:      {mode: rel_tol, tol: 0.005}   # sai số 0,5% do làm tròn
    ratio:    {mode: round,   decimals: 4}
    percent:  {mode: round,   decimals: 1, alias: [ratio_x100]}
    count:    {mode: exact}
  allowlist:
    years:    {min: 2000, max: 2100}
    ordinals: {min: 1, max: 10}
    literals: [0, 1, 2, 100]
  aliases:
    "tỷ":     1_000_000_000
    "triệu":  1_000_000
    "nghìn":  1_000
```

`alias: [ratio_x100]` xử lý EvidenceSet lưu `0.488` nhưng câu trả lời viết `48,8%`.

| Chỉ số | Ngưỡng |
|---|---|
| `numeric_grounding_rate` | **phải = 1,0** (hard fail) |
| `ungrounded_number_count` | **phải = 0** |
| `bare_number_count` | ≤ 2 → cảnh báo, không chặn |

### L3 — Entity grounding

```python
# app/verify/entity.py

def check_entity_grounding(text: str, ev: EvidenceSet, catalog, cfg) -> CheckResult:
    known = ev.all_string_values() | catalog.all_dimension_values()  # cache 5 phút
    mentioned = extract_proper_nouns_vi(text)   # tên hoa, mã CMP-*, CUS-*
    unknown = [m for m in mentioned if not _is_known(m, known, threshold=0.92)]
    return CheckResult(
        name="entity_grounding", passed=not unknown,
        score=1 - len(unknown)/max(len(mentioned), 1),
        details={"unknown_entities": unknown}, severity=Severity.BLOCK
    )
```

Trích tên riêng tiếng Việt (`vi_text.py`):
1. Mã định danh: regex `CMP-*`, `CUS-*`, `PRD-*`, `APP-*`, `LEAD-*`
2. Chuỗi ≥ 2 từ liên tiếp viết hoa chữ đầu: "Broker Network", "Zalo Remarketing"
3. Fuzzy match `difflib.get_close_matches` threshold 0,92

Cũng kiểm tra **caveat bắt buộc**: nếu EvidenceSet có chỉ số mang `caveat_vi`
mà câu trả lời không nhắc → WARN + tự chèn caveat.

### L4 — Stats guard

```python
# app/verify/stats_guard.py

def check_stats_guard(text: str, ev: EvidenceSet, cfg) -> CheckResult:
    has_significant = any(c.significant for c in ev.comparisons)
    unsupported = []
    causal_without_evidence = []
    for sentence in split_sentences_vi(text):
        if has_comparative_marker(sentence) and not has_significant:
            unsupported.append(sentence)
        if has_causal_marker(sentence) and not has_correlation_phrase(sentence):
            causal_without_evidence.append(sentence)
    ...
```

Marker so sánh (`config/verify.yaml`):
```yaml
comparative_markers_vi:
  - "cao hơn" - "thấp hơn" - "tốt hơn" - "kém hơn"
  - "vượt trội" - "dẫn đầu" - "tốt nhất" - "kém nhất"
  - "hiệu quả hơn" - "gấp" - "nhất" - "hơn hẳn"
causal_markers_vi:
  - "vì" - "do" - "dẫn đến" - "khiến" - "nhờ" - "gây ra" - "làm cho"
```

Cỡ mẫu:
| Quy tắc | Ngưỡng | Hành vi |
|---|---|---|
| `min_sample_size` cho tỷ lệ | 30 | n < 30 → `INSUFFICIENT_SAMPLE` |
| Cảnh báo cỡ mẫu | n < 100 | Trả số + bắt buộc kèm CI |
| CI Wilson cho mọi tỷ lệ | luôn | `20,7% (CI95: 18,0%–23,7%, n=797)` |

**Skew guard** (lớp con): kích hoạt khi `|mean − median| / |mean| > 0,3` hoặc tỷ lệ âm > 30%.
Khi kích hoạt, chỉ số trung bình **phải** kèm median và negative_share.

### L5 — LLM judge (bất đồng bộ)

Chạy **sau** `done`, trên cùng kết nối SSE. `temperature=0`, `max_tokens=200`.
Trả 3 nhãn: `SUPPORTED` / `CONTRADICTED` / `NOT_ENOUGH_INFO`.

| Tín hiệu | Hành vi |
|---|---|
| `contradiction_rate > 0` | **BLOCK** |
| `neutral_rate > 0.3` | **HEDGE** |
| `entailment_rate ≥ 0.9` | **PASS** |

Vì trần 10 RPM, judge chạy nền — huy hiệu Trust hiện `đang kiểm tra`, cập nhật qua
SSE `event/judge` khi xong.

### L6 — Trust Score

```python
# app/verify/pipeline.py

def compute_trust(checks: dict, cfg) -> TrustScore:
    hard_fail = [c for c in checks.values()
                 if c.severity == "BLOCK" and not c.passed]
    if hard_fail:
        return TrustScore(value=0.0, band=Band.BLOCKED,
                          reasons=[c.name for c in hard_fail])
    value = (cfg.w_schema  * checks["sql_validation"].score
           + cfg.w_numeric * checks["numeric_grounding"].score
           + cfg.w_entity  * checks["entity_grounding"].score
           + cfg.w_stats   * checks["stats_guard"].score
           + cfg.w_judge   * checks.get("judge", Judge(entailment_rate=1.0)).entailment_rate
           + cfg.w_consist * checks.get("self_consistency", Consist(1.0)).top_cluster_share
           ) / cfg.total_weight
    if value >= cfg.t_high: band = Band.PASS
    elif value >= cfg.t_low: band = Band.HEDGE
    else: band = Band.ABSTAIN
    return TrustScore(value=value, band=band, components=checks)
```

Trọng số (`config/verify.yaml`):
```yaml
weights:
  schema: 0.15      # L0 (tất định)
  numeric: 0.25     # L2 (tất định, quan trọng nhất)
  entity: 0.10      # L3 (tất định)
  stats: 0.20       # L4 (tất định)
  judge: 0.20       # L5 (LLM)
  consistency: 0.10 # self-consistency (freeform only)
thresholds:
  t_high: 0.85      # hiệu chỉnh trên golden set
  t_low:  0.60
alpha: 0.05
min_effect_size: 0.2
min_sample_size: 30
```

Bốn band đầu ra:

| Band | Huy hiệu | UI |
|---|---|---|
| `PASS` | 🟢 Đã kiểm chứng | Câu trả lời đầy đủ |
| `HEDGE` | 🟡 Hạn chế tin cậy | Câu trả lời + rào đón + bảng số mở |
| `ABSTAIN` | ⚪ Từ chối | Chỉ bảng số thô |
| `BLOCKED` | 🔴 Bị chặn | Sinh lại 1 lần; vẫn fail → chỉ bảng số |

### L7 — Policy enforcement trên Gateway

Khi agent dùng Resource Gateway (MCP) cho tool calling, mỗi `tools/call`
được đánh giá against Policy Group. `tools/list` luôn allowed.

Action vocabulary: `target__method` (vd: `hr__lookup_employee`).

> Policy deny = tool không gọi = không có dữ liệu = EvidenceSet không có fact
> → L2 tự động chặn nếu narrator cố dùng số từ tool bị deny.

### Streaming verification (kiểm chứng theo khối)

```python
# app/agent/streaming.py

FLUSH_ON = ("\n\n", "\n### ", "\n## ", "\n- ", "\n* ", "\n1. ")

class StreamingVerifier:
    """Gom token thành khối markdown hoàn chỉnh, thay thẻ, kiểm chứng,
    rồi mới phát ra. Không bao giờ để lọt thẻ chưa phân giải lên màn hình."""

    def __init__(self, evidence, catalog, policy, max_block_chars=600):
        self._buf = ""
        self._seq = 0
        self._blocks = []

    def feed(self, token: str):
        self._buf += token
        while (cut := self._find_safe_cut()) is not None:
            yield self._emit(self._buf[:cut])
            self._buf = self._buf[cut:]

    def finish(self):
        if self._buf.strip():
            yield self._emit(self._buf)
        self._buf = ""

    def _find_safe_cut(self):
        """Vị trí cắt AN TOÀN, hoặc None. KHÔNG cắt giữa thẻ {{...}}."""
        if self._has_open_tag():
            open_at = self._buf.rfind("{{")
            region = self._buf[:open_at]
        else:
            region = self._buf
        best = max((region.rfind(m) for m in FLUSH_ON), default=-1)
        if best >= 0: return best + 1
        if len(region) > self.max_block_chars:
            return region.rfind(" ", 0, self.max_block_chars) or None
        return None

    def _has_open_tag(self):
        o, c = self._buf.rfind("{{"), self._buf.rfind("}}")
        return o > c

    def _emit(self, raw):
        repaired = self._repair_tags(raw, self.evidence)
        md, unresolved = self.evidence.substitute(repaired)
        num = check_numeric_grounding(md, self.evidence, self.policy)
        ent = check_entity_grounding(md, self.evidence, self.catalog)
        ok = not unresolved and num.passed and ent.passed
        self._seq += 1
        return BlockEvent(seq=self._seq, md=md if ok else None,
                          md_raw=md, verified=ok,
                          reason=... if not ok else None)
```

### Tag repair

Model nhỏ hay viết `{{F2_1.r1.romi}}` thay vì `{{F2.r1.approval_rate}}`.

```python
_REPAIR_RE = re.compile(r"\{\{(F\d+)_(\d+)(\.[^}]+)\}\}")

def _repair_tags(text, ev):
    def _try_repair(m):
        original = m.group(1) + "_" + m.group(2) + m.group(3)
        repaired = m.group(1) + m.group(3)
        if ev.resolve(original) is not None: return m.group(0)  # gốc OK → không sửa
        if ev.resolve(repaired) is not None: return "{{" + repaired + "}}"  # repaired OK
        return m.group(0)  # cả hai không resolve → giữ nguyên
    return _REPAIR_RE.sub(_try_repair, text)
```

An toàn: chỉ repair khi tag gốc không resolve AND tag repaired resolve.

### Narrator enhancement

Chèn reminder explicit trong user message, **trước** evidence:

```
DANH SÁCH fact_id PHÉP DÙNG (chỉ những cái này, không thêm số thứ tự):
  F1, F2, F3, F4, C1

TUYỆT ĐỐI KHÔNG:
  - Viết chữ số trực tiếp (sai: 'ROMI 6,20' | đúng: 'ROMI {{F1.r1.romi}}')
  - Dùng fact_id không có trong danh sách (sai: 'F2_1' | đúng: 'F2')
  - Ghép thêm hậu tố (sai: 'F1b', 'F2_1' | đúng: 'F1', 'F2')
  - Đặt tên thực thể khác EVIDENCE (sai: 'Zalo ZNS' | đúng: tên nguyên văn)

Tên thực thể có trong dữ liệu (phải dùng nguyên văn):
  Vay Lai - Zalo Remarketing, Vay Tieu Dung - Broker Network, ...
```

### Danh mục lỗi và lớp bắt

| # | Kiểu lỗi | Ví dụ | Lớp bắt |
|---|---|---|---|
| H1 | Bịa số | "ROMI = 2,4" (thật: 1,31) | L2 |
| H2 | Trích sai số | Lấy `net_profit` dòng khác | L2 |
| H3 | Lẫn đơn vị | "6,2%" cho ROMI 6,20 lần | L2 (policy) |
| H4 | Bịa tên | "chiến dịch Instagram Stories" | L3 |
| H5 | So sánh trên nhiễu | "Freelancer sinh lời nhất" | L4 |
| H6 | Mẫu quá nhỏ | Kết luận từ n=29 | L4 |
| H7 | Suy nhân quả | "Cài app làm tăng lợi nhuận" | L4 + L5 |
| H8 | Bỏ caveat | Nêu tỷ lệ tổng hợp mà không nói | L3 |
| H9 | Bịa cột SQL | `fact_loan.campaign_id` | L0 |
| H10 | Sai mẫu số | `SUM/COUNT(*)` gồm hồ sơ bị từ chối | Semantic layer |
| H11 | Ngoại suy thời gian | "So sánh tháng 8 vs tháng 7" | DQ-03 + L4 |
| H12 | Diễn giải bảng rỗng | "Doanh thu tăng 12%" khi không có dòng | L2 + L6 |
| H13 | Lạc đề | Trả lời chuyện không được hỏi | L5 |
| H14 | Đọc ngược dấu | Gọi ROMI −1,85 là "hiệu quả" | L5 |
| H15 | Trung bình che cơ cấu | "TB 199k" mà không nói median −86k | L4 skew guard |
| H16 | Ngoại suy tuyến tính | "1000 khách ≈ 200 triệu" | L4 skew guard |
| H17 | Chỉ số hư danh | "Broker lead→hồ sơ cao nhất nên tốt nhất" | L4 + playbook |
| H18 | Hallucinate fact_id | `{{F2_1.r1.romi}}` | Tag repair + L2 |
| H19 | Viết số thẳng | "ROMI 6,20" thay vì thẻ | L2 (bare number) |

### Telemetry

Mỗi lượt trả lời ghi `ops.agent_trace`:
```jsonc
{
  "trace_id": "8f14e45f-...",
  "question": "Chiến dịch nào đang lỗ?",
  "intent": "campaign_overview",
  "decision": "ANSWERED",
  "trust_score": 0.94,
  "trust_band": "PASS",
  "checks": {
    "numeric_grounding": {"passed": true, "score": 1.0, "resolved": 12},
    "entity_grounding":  {"passed": true, "score": 1.0},
    "stats_guard":       {"passed": true, "score": 1.0},
    "judge": {"entailment_rate": 0.92, "contradiction_rate": 0.0}
  },
  "prompt_version": "1.0.0",
  "model_name": "qwen-3.6-flash",
  "profile": "greennode",
  "llm_calls": 2,
  "latency_ms": 5400
}
```

Ba cột bắt buộc: `prompt_version`, `model_name`, `profile`.

---

## Phase 1 phụ — SSE Streaming

### Bảng sự kiện SSE

```
POST /api/chat        Content-Type: application/json
Accept: text/event-stream
```

| `event` | Khi nào | `data` |
|---|---|---|
| `stage` | Vào giai đoạn mới | `{stage, label, progress, elapsed_ms}` |
| `plan` | Sau PLAN | `{metrics, filters, date_range}` |
| `evidence` | Sau COMPUTE, trước LLM | `{facts, data_version}` |
| `table` | Bảng số hiển thị ngay | `{fact_id, columns, rows}` |
| `chart` | Cấu hình biểu đồ | `{fact_id, type, option}` |
| `block` | Khối markdown đã kiểm chứng | `{seq, md, verified, numbers:{ok,total}}` |
| `warning` | Khối không qua / cảnh báo | `{level, code, message}` |
| `verified` | Sau VERIFY (L0–L4) | `{trust, band, checks}` |
| `judge` | **Sau `done`** — L5 async | `{entailment_rate, contradiction_rate, trust}` |
| `artifact` | File xuất ra | `{kind:"csv", url, filename, rows}` |
| `done` | Kết thúc | `{trace_id, decision, latency_ms, llm_calls}` |
| `error` | Lỗi không phục hồi | `{code, message, retryable}` |
| `:` (comment) | Keep-alive mỗi 15 giây | — |

Thứ tự quan trọng: **`evidence` và `table` đến trước `block`**.
Người dùng thấy bảng số **trước khi** LLM viết xong.

### Thông báo tiến trình (`config/stages.yaml`)

```yaml
version: "1.0.0"

stages:
  intake:     { label_vi: "Đang đọc câu hỏi", weight: 1 }
  routing:    { label_vi: "Đang xác định loại phân tích", weight: 1 }
  planning:   { label_vi: "Đang chọn chỉ số cần tính", weight: 1 }
  computing:  { label_vi: "Đang truy vấn dữ liệu", weight: 4,
                template_vi: "Đang truy vấn {n_metrics} chỉ số trên {n_rows} dòng" }
  analyzing:  { label_vi: "Đang kiểm định thống kê", weight: 2 }
  narrating:  { label_vi: "Đang viết phân tích", weight: 6 }
  verifying:  { label_vi: "Đang đối chiếu số liệu với nguồn", weight: 2 }
  rendering:  { label_vi: "Đang hoàn thiện", weight: 1 }
  judging:    { label_vi: "Đang kiểm tra lại bằng mô hình", weight: 0 }

playbook_overrides:
  campaign_overview:
    computing: "Đang tạo dashboard hiệu quả chiến dịch"
    narrating: "Đang tóm tắt kết quả từng chiến dịch"
  campaign_diagnosis:
    computing: "Đang phân rã chi phí và phễu của chiến dịch"
    narrating: "Đang viết chẩn đoán"
  customer_persona:
    computing: "Đang dựng chân dung các tập khách hàng"
    analyzing: "Đang tính CLV và khoảng tin cậy"
    narrating: "Đang mô tả chân dung"
  clv_actions:
    computing: "Đang tìm cơ hội tăng giá trị vòng đời"
    narrating: "Đang soạn khuyến nghị"

special:
  rate_limited:   "Đang chờ lượt gọi mô hình, khoảng {wait_s} giây"
  repairing:      "Truy vấn chưa đúng, đang sửa lại (lần {attempt}/3)"
  regenerating:   "Kết quả chưa đạt kiểm chứng, đang viết lại"
  cache_hit:      "Dùng lại kết quả đã tính"
  degraded_llm:   "Mô hình tạm không phản hồi — hiển thị số liệu dạng rút gọn"
```

### Keep-alive

```python
return EventSourceResponse(
    event_generator(request, state),
    ping=15,
    headers={"Cache-Control": "no-cache", "X-Accel-Buffering: no",
             "Connection": "keep-alive"},
)
```

### Client-side

```javascript
async function ask(question, history) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept": "text/event-stream",
      "X-GreenNode-AgentBase-User-Id": userId,
      "X-GreenNode-AgentBase-Session-Id": sessionId,
    },
    body: JSON.stringify({message: question, history}),
    signal: state.abort.signal,
  });

  const msg = appendAssistantMessage();

  for await (const ev of parseSSE(res.body)) {
    switch (ev.event) {
      case "stage":     msg.setStage(ev.data.label, ev.data.progress); break;
      case "plan":      msg.setPlan(ev.data); break;
      case "evidence":  msg.setEvidenceSummary(ev.data.facts); break;
      case "table":     msg.appendTable(ev.data); break;
      case "chart":     msg.appendChart(ev.data); break;
      case "block":
        ev.data.verified ? msg.appendBlock(ev.data.md)
                         : msg.appendBlockedBlock(ev.data);
        break;
      case "warning":   msg.addWarning(ev.data); break;
      case "verified":  msg.setTrustBadge(ev.data); break;
      case "judge":     msg.updateTrustBadge(ev.data); break;
      case "artifact":  msg.addDownload(ev.data); break;
      case "done":      msg.finalize(ev.data); break;
      case "error":     msg.showError(ev.data); break;
    }
    scrollToBottomIfPinned();
  }
}
```

Bốn chi tiết UX:
1. Chỉ tự cuộn khi người dùng đang ở đáy
2. Thanh tiến trình chạy theo `weight` cộng dồn
3. `judge` đến sau `done` — huy hiệu cập nhật tại chỗ
4. Nút Dừng luôn hiện, gọi `state.abort.abort()`

---

## Phase 2 — TEST & DEPLOY

### Step 7/9: Local Testing

```
/agentbase-wizard test validate    # static analysis
/agentbase-wizard test local       # start server + contract tests
/agentbase-wizard test docker      # build image + test in container
/agentbase-wizard test preflight   # integration readiness
```

#### Validate checks

| Check | Kỳ vọng |
|---|---|
| Python version | ≥ 3.10 |
| Dockerfile EXPOSE 8080 | ✅ |
| Entrypoint imports GreenNodeAgentBaseApp | ✅ |
| GET /health returns 200 | ✅ |
| .dockerignore excludes .env, .greennode.json | ✅ |
| requirements.txt includes greennode-agentbase | ✅ |

#### Local test

```bash
# 1. Venv + deps
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows
pip install -r requirements.txt

# 2. ETL (chạy một lần, hoặc khi dữ liệu đổi)
python -m etl.load_excel --source excel
python -m etl.build_marts
python -m etl.dq_checks

# 3. Start
$env:APP_PROFILE = "local"
python main.py

# 4. Test
curl http://127.0.0.1:8080/health     # {"status":"ok"}
curl http://127.0.0.1:8080/readyz     # {"db":"ok","dq":"ok","catalog":"ok"}
curl http://127.0.0.1:8080/api/dashboard/campaigns
curl -X POST http://127.0.0.1:8080/invocations `
  -H "Content-Type: application/json" `
  -H "X-GreenNode-AgentBase-User-Id: test-user" `
  -H "X-GreenNode-AgentBase-Session-Id: test-session" `
  -d '{\"message\":\"Chiến dịch nào đang lỗ?\"}'
```

#### Anti-hallucination gates (chạy trước khi deploy)

```bash
python scripts/validate_artifacts.py
python scripts/verify_metrics_duckdb.py
ruff check . && mypy app/semantic app/verify app/analytics && lint-imports
pytest tests/ -q
python -m evals.run_eval --split dev --profile test
```

Ba cổng **cứng**:
- `numeric_grounding_rate` = **1,000**
- `must_not_mention_violations` = **0**
- Không có DQ mức `BLOCK` fail

### Step 8/9: Deploy

```
/agentbase-deploy
```

#### 8a. Docker registry — AgentBase managed CR

```bash
bash .claude/skills/agentbase/scripts/cr.sh credentials docker-login
# Secret không ghi ra disk — pipe qua --password-stdin
```

Xem repo info:
```bash
bash .claude/skills/agentbase/scripts/cr.sh repo get
# → registryUrl + repoName (dùng để tag image)
```

#### 8b. Build + push

```bash
# Lấy registryUrl + repoName từ cr.sh repo get
REGISTRY=vcr.vngcloud.vn
REPO=<repoName>
IMAGE=$REGISTRY/$REPO/mkt-insight-agent-v2
TAG=v$(Get-Date -Format "yyyyMMddHHmmss")   # Windows PowerShell
# TAG=v$(date +%Y%m%d%H%M%S)                  # macOS/Linux

docker build --platform linux/amd64 -t $IMAGE:$TAG .
docker push $IMAGE:$TAG
```

> **Bắt buộc `linux/amd64`** — node runtime là amd64.

#### 8c. Tạo/cập nhật runtime

```bash
# Kiểm tra wallet POC
bash .claude/skills/agentbase/scripts/billing.sh can-use-poc

# List flavors
bash .claude/skills/agentbase/scripts/runtime.sh flavors
# → chọn flavor có supportedResourceTypes chứa "agent-runtime" (PUBLIC mode)

# Check runtime existing
bash .claude/skills/agentbase/scripts/runtime.sh list
```

**Nếu runtime mới:**
```bash
bash .claude/skills/agentbase/scripts/runtime.sh create \
  --name "mkt-insight-agent-v2" \
  --image "$IMAGE:$TAG" \
  --flavor "1x1-general" \
  --env-file .env \
  --poc true \
  --from-cr \
  --min-replicas 1 --max-replicas 2 \
  --cpu-scale 60 --mem-scale 70
```

**Nếu update runtime existing:**
```bash
bash .claude/skills/agentbase/scripts/runtime.sh update <RUNTIME_ID> \
  --image "$IMAGE:$TAG" \
  --flavor "1x1-general" \
  --env-file .env \
  --from-cr
```

#### 8d. Chờ ACTIVE + test

```bash
bash .claude/skills/agentbase/scripts/runtime.sh get <RUNTIME_ID>
# → status: ACTIVE

bash .claude/skills/agentbase/scripts/runtime.sh endpoints list <RUNTIME_ID>
# → lấy url từ DEFAULT endpoint

curl -s -o /dev/null -w "%{http_code}" "<endpoint-url>/health"   # 200
```

#### Auto-injected env vars (KHÔNG đặt tay)

| Variable | Description |
|---|---|
| `GREENNODE_CLIENT_ID` | IAM service account — managed by runtime |
| `GREENNODE_CLIENT_SECRET` | IAM secret — never hardcode/log |
| `GREENNODE_AGENT_IDENTITY` | Agent identity — SDK dùng để retrieve outbound auth |
| `GREENNODE_ENDPOINT_URL` | Endpoint URL — cho self-referencing callbacks |

### Step 9/9: Verify

```bash
# Runtime
bash .claude/skills/agentbase/scripts/runtime.sh get <RUNTIME_ID>

# Health + readiness
curl <url>/health    # 200
curl <url>/readyz    # 200, db=ok, dq=ok

# UI — mở <url>/ trong browser

# Dashboard data
curl <url>/api/dashboard/campaigns

# Invocation
curl -X POST <url>/invocations \
  -H "Content-Type: application/json" \
  -H "X-GreenNode-AgentBase-User-Id: test-user" \
  -H "X-GreenNode-AgentBase-Session-Id: test-session" \
  -d '{"message": "Chiến dịch nào đang lỗ?"}'
```

---

## Phase 3 — OPERATE

### 3.1 Monitor

```
/agentbase-monitor
```

#### Runtime logs
```bash
bash .claude/skills/agentbase/scripts/runtime.sh logs <RUNTIME_ID> \
  --from 0 --limit 100 --query "error"
```

#### Endpoint logs
```bash
bash .claude/skills/agentbase/scripts/runtime.sh endpoints logs <RUNTIME_ID> <ENDPOINT_ID>
```

#### Metrics (CPU/RAM)
```bash
bash .claude/skills/agentbase/scripts/runtime.sh endpoints metrics <RUNTIME_ID> <ENDPOINT_ID>
```

#### Infrastructure events (khi endpoint không ACTIVE mà logs trống)
```bash
bash .claude/skills/agentbase/scripts/runtime.sh endpoints events <RUNTIME_ID> <ENDPOINT_ID>
```

Event signatures:
| Message | Nghĩa | Next step |
|---|---|---|
| `ErrImagePull` | Image không pull được | Verify imageUrl + registry auth |
| `OOM` | Vượt memory limit | Tăng flavor hoặc fix memory leak |
| `probe failed` | `/health` không 200 | Verify health endpoint |
| `insufficient` / `no capacity` | Không đủ capacity | Thử flavor nhỏ hơn |

#### Dashboard (tổng quan)
```bash
bash .claude/skills/agentbase/scripts/discovery.sh
```

#### Bảng theo dõi chất lượng (`GET /admin/quality`)

| Chỉ số | Mục tiêu |
|---|---|
| `numeric_grounding_rate` | **1,000** |
| `block_rate` | < 5% |
| `abstain_rate` | 5–15% |
| `hedge_rate` | < 25% |
| `avg_trust_score` | > 0,88 |
| `judge_contradiction_rate` | < 1% |
| `p95_latency_ms` | < 8 000 |
| `llm_calls_per_answer` | ≤ 2 |

### 3.2 Resource Gateway (MCP)

```
/agentbase-gateway create
```

Tham số:
- **name**: `mkt-insight-v2-gateway` (3–40 chars, `^[a-z0-9-]+$`)
- **networkMode**: `PUBLIC` (mặc định)
- **flavorId**: từ `GET /flavors?resourceType=GATEWAY`
- **replicas**: 1–10
- **inboundAuth**: `NONE` / `IAM` / `JWT`
- **targets**: MCP server list (mỗi target: `name`, `endpoint`, `outboundAuth`)
- **policyGroupId**: (optional) bind Policy Group

Outbound auth types: `NONE`, `APIKEY` (2LO/3LO), `OAUTH` (2LO/3LO).
Secret lưu qua `/agentbase-identity`, gateway chỉ giữ `providerName`.

### 3.3 Policy

```
/agentbase-policy group create --name mkt-insight-v2-policies
/agentbase-policy policy create --group-id <group-id>
```

Statement: `effect` (allow/deny) + `principal` + `actions` + `resources` + `condition`.

9 condition operators: `equals`, `notEquals`, `in`, `like`, `contains`,
`lessThan`, `lessThanOrEqual`, `greaterThan`, `greaterThanOrEqual`.

> **Deny-wins.** Quota: max 20 groups/user, 10 policies/group.
> `tools/list` luôn allowed (bypass).

---

## Phase 4 — ADVANCED

### 4.1 Container Registry

```bash
bash .claude/skills/agentbase/scripts/cr.sh repo get           # repo info
bash .claude/skills/agentbase/scripts/cr.sh credentials get    # credentials
bash .claude/skills/agentbase/scripts/cr.sh images list        # list images
bash .claude/skills/agentbase/scripts/cr.sh artifacts list --image <name>
```

### 4.2 Rollback

```bash
bash .claude/skills/agentbase/scripts/runtime.sh versions <RUNTIME_ID>
bash .claude/skills/agentbase/scripts/runtime.sh update <RUNTIME_ID> \
  --image "<previous-image-url>" --flavor "<previous-flavor>"
```

### 4.3 Canary

```bash
bash .claude/skills/agentbase/scripts/runtime.sh endpoints create <RUNTIME_ID> \
  --name "canary" --version <new-version-number>
# Test trên canary URL, rồi update runtime
```

---

## API endpoints

| Method | Path | Mục đích |
|---|---|---|
| `GET` | `/health` | Process sống (luôn 200) — **bắt buộc bởi AgentBase** |
| `GET` | `/readyz` | Sẵn sàng: DB + DQ + catalog |
| `POST` | `/invocations` | Quy ước SDK — non-streaming, cho Zalo/API ngoài |
| `GET` | `/` | UI: dashboard + chat |
| `GET` | `/api/dashboard/summary` | KPI tổng |
| `GET` | `/api/dashboard/campaigns` | Bảng chiến dịch |
| `GET` | `/api/dashboard/funnel` | Dữ liệu phễu |
| `GET` | `/api/dashboard/trend` | Chuỗi theo ngày |
| `GET` | `/api/segments` | Bảng phân khúc + CLV |
| `GET` | `/api/segments/{id}/customers.csv` | Xuất CSV cho CRM |
| `GET` | `/api/actions` | Khuyến nghị D3 |
| `POST` | `/api/chat` | Hỏi đáp **SSE stream** |
| `GET` | `/api/trace/{trace_id}` | Bằng chứng đầy đủ |
| `GET`/`PUT` | `/api/admin/prompts[/{id}]` | Xem/sửa prompt |
| `GET`/`PUT` | `/api/admin/metrics` | Xem/sửa catalog chỉ số |
| `GET` | `/api/admin/quality` | Bảng theo dõi chất lượng |
| `POST` | `/api/admin/etl/run` | Chạy lại ETL |

---

## Checklist nghiệm thu

### Platform

| Kiểm tra | Kỳ vọng |
|---|---|
| Console Agent Runtime | `ACTIVE` |
| `GET <url>/health` | 200 `{"status":"ok"}` |
| `GET <url>/readyz` | 200, `db=ok`, `dq=ok` |
| `GET <url>/` | UI hiện, dashboard có số |
| `POST <url>/invocations` | `answer_markdown` + `evidence` + `trust` |
| Vùng chat UI | Không vượt 60% chiều cao màn hình |
| `runtime.sh logs` | Không có ERROR lặp |

### Anti-hallucination

| Kiểm tra | Kỳ vọng |
|---|---|
| `numeric_grounding_rate` | **= 1,000** |
| `must_not_mention_violations` | **= 0** |
| DQ mức BLOCK | **0 fail** |
| `pytest tests/ -q` | All pass |
| `evals.run_eval --split dev` | All pass |

### Memory

| Kiểm tra | Kỳ vọng |
|---|---|
| Memory store tồn tại | `discovery.sh` list được |
| Short-term memory | Câu hỏi lặp nhớ context |
| Long-term memory | Facts lưu + retrieve được |
| Headers | `User-Id` + `Session-Id` có mặt |

### Identity

| Kiểm tra | Kỳ vọng |
|---|---|
| Agent identity tồn tại | `identity list` thấy |
| Outbound auth | API key retrieve được tại runtime |

### Gateway + Policy

| Kiểm tra | Kỳ vọng |
|---|---|
| Gateway `ACTIVE` | `GET /gateways/{name}` state=ACTIVE |
| Policy Group | `GET /policy-groups` thấy |
| `tools/call` qua gateway | Được evaluate against policy |
| `tools/list` | Always allowed |

### Database + LLM + IAM

| Kiểm tra | Kỳ vọng |
|---|---|
| IAM token | `get_token.sh` trả JWT hợp lệ |
| IAM Client ID | `cc69d86b-d8ea-4ab4-8e12-539563b470c1` |
| DB connection | `readyz` → `db=ok` |
| DB host | `49.213.71.93:5432` |
| DB name | `mkt_insight` |
| LLM endpoint | `maas-llm-aiplatform-hcm.api.vngcloud.vn/v1` |
| LLM model | Qwen 3.6 Flash (field `path` từ models list) |
| LLM 401 | Key ACTIVE, model ENABLED |
| LLM 429 | Không liên tục (≤ 2 calls/answer) |

---

## Script một lệnh deploy

```powershell
# scripts/deploy.ps1
param(
  [Parameter(Mandatory)][string]$Version,
  [string]$RuntimeId
)
$ErrorActionPreference = "Stop"

$REGISTRY = "vcr.vngcloud.vn"
$REPO = (bash .claude/skills/agentbase/scripts/cr.sh repo get | jq -r '.name')
$IMAGE = "$REGISTRY/$REPO/mkt-insight-agent-v2"

# 1. Gate kiểm chứng (TRƯỚC khi build)
python scripts/validate_artifacts.py
python scripts/verify_metrics_duckdb.py
ruff check .
mypy app/semantic app/verify app/analytics
pytest tests/ -q
python -m evals.run_eval --split dev --profile test

# 2. Build
docker build --platform linux/amd64 -t "$IMAGE:$Version" .

# 3. Login + push
bash .claude/skills/agentbase/scripts/cr.sh credentials docker-login
docker push "$IMAGE:$Version"

# 4. Update runtime
bash .claude/skills/agentbase/scripts/runtime.sh update $RuntimeId `
  --image "$IMAGE:$Version" --from-cr --env-file .env

# 5. Chờ ACTIVE + verify
bash .claude/skills/agentbase/scripts/runtime.sh get $RuntimeId
$url = bash .claude/skills/agentbase/scripts/runtime.sh endpoints url --runtime-id $RuntimeId
curl -fsS "$url/health"
curl -fsS "$url/readyz"
Write-Host "==> Deployed: $url"
```

---

## Xử lý sự cố

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| 401 Unauthorized (platform API) | IAM token hết hạn hoặc sai credentials | `get_token.sh --force`; verify `GREENNODE_CLIENT_ID` = `cc69d86b-...` |
| 403 Forbidden | Service account thiếu policies | Attach `AgentBaseFullAccess` + `vcrFullAccess` + `AiPlatformFullAccess` tại IAM console |
| Runtime `CREATING` → `ERROR` | Image không pull (sai URL/auth) hoặc sai arch | `cr.sh repo get`; build `--platform linux/amd64` |
| `ACTIVE` nhưng timeout | App nghe `127.0.0.1` thay vì `0.0.0.0` | Kiểm tra `host` trong `app.run()` |
| `/health` fail, restart loop | `/health` chạm DB | `/health` chỉ kiểm tra process; `/readyz` cho DB |
| `/readyz` 503, `db=fail` | Security Group chặn IP runtime | Mở SG cho egress IP runtime |
| LLM 401 | Key chưa `ACTIVE` hoặc model chưa enable | `aip.sh api-keys list`, `aip.sh models list --status ENABLED` |
| LLM 429 liên tục | Đụng trần 10 RPM | Hạ rate_limit, bật cache, tắt self-consistency |
| Memory error: missing headers | Thiếu User-Id/Session-Id | Thêm cả hai header |
| Gateway 502 | Target unreachable hoặc outbound auth sai | Verify target endpoint + outboundAuth |
| Policy deny legitimate caller | `deny` match hoặc no `allow` match | Review với `/agentbase-policy` |
| Câu trả lời bị chặn liên tục | Narrator viết số trực tiếp | Xem prompt config, **đừng tắt L2** |
| `OOMKilled` | Flavor quá nhỏ | Tăng flavor qua `runtime.sh update` |
| Dashboard trống | ETL chưa chạy trên DB | Chạy `etl.*` — DB dùng chung nên prod thấy ngay |
| Số trên prod khác local | Không thể nếu chung DB | Kiểm tra `MKT_DATABASE__URL` hai bên trỏ cùng instance |
