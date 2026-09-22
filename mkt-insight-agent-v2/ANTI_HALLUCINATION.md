# Hệ thống Anti-Hallucination — Marketing Insight Agent v2

> Mô tả triển khai thực tế 7+1 lớp chống hallucination, cập nhật sau khi debug,
> tối ưu và hardening lần 2 (severity dual-mode, disambiguation, VI number format,
> streaming UX, fallback chain, prompt defense-in-depth).

---

## Tổng quan

Agent trả lời 3 câu hỏi nghiệp vụ: dashboard hiệu quả chiến dịch, chân dung khách hàng, hành động nâng cao CLV. Nguyên tắc thiết kế số 1: **code tính toán — LLM chỉ diễn giải**. Mọi con số đến từ SQL đã viết sẵn, LLM phát số dưới dạng thẻ `{{F1.r1.romi}}`, hệ thống thay thẻ bằng giá trị thật trước khi hiển thị.

---

## Kiến trúc 7+1 lớp

```
Câu hỏi user
    │
    ▼
┌─ L0: SQL AST Guard (sqlguard.py) ──────────────────┐
│  sqlglot parse → chặn DML/DDL, bảng không cho phép,  │
│  thiếu LIMIT. Chỉ cho freeform SQL.                  │
│  Template/preset query BYPASS L0 (đã review dev-time)│
│  Tất định · ~5ms · 0 LLM call                        │
└───────────────────────────────────────────────────────┘
    │
    ▼
┌: L1: EXPLAIN Dry-run (sqlguard.py) ────────────────┐
│  EXPLAIN trên DB → bắt lỗi kiểu, truy vấn nặng.       │
│  Chỉ cho freeform SQL.                                │
│  Template/preset query BYPASS L1 (đã review dev-time)│
│  Tất định · ~20ms · 0 LLM call                       │
└───────────────────────────────────────────────────────┘
    │
    ▼
┌─ ROUTE → PLAN → COMPUTE → NARRATE ──────────────────┐
│  LLM stream tokens với thẻ {{fact_id.row.col}}       │
└───────────────────────────────────────────────────────┘
    │
    ▼
┌─ Auto-tag (streaming.py) ───────────────────────────┐
│  Sau khi LLM viết, quét bare numbers trong text,      │
│  match với evidence values (tol 2%), thay bằng thẻ.   │
│  Xử Decimal từ DB (float(Decimal)).                   │
│  Tất định · ~1ms · 0 LLM call                        │
└───────────────────────────────────────────────────────┘
    │
    ▼
┌─ L2: Numeric Grounding / PCN (numeric.py) ──────────┐
│  Proof-Carrying Numbers:                              │
│  1. Trích tất cả {{...}} → kiểm tra resolve           │
│  2. Thay thẻ → số, quét bare numbers                  │
│  3. Allowlist: năm (2000-2100), ordinal (1-10),       │
│     literal (0,1,2,100), % thống kê (95,90,99,80,75)  │
│  4. Policy match: rel_tol 0.5% cho VND                │
│  5. Xử Decimal: isinstance(v, Decimal) → float(v)    │
│  T8 Tất định · ~1ms · 0 LLM call · severity=BLOCK    │
└───────────────────────────────────────────────────────┘
    │
    ▼
┌─ L3: Entity Grounding (entity.py) ──────────────────┐
│  1. Trích proper nouns: regex mã (CMP-*, CUS-*),    │
│     chuỗi 2+ từ viết hoa, first letter dùng         │
│     [_VI_UPPER] = A-Z + chữ hoa Việt có dấu         │
│     (ÀÁÂẦẨẪẬĐÈÉÊỀỂỄỆÌÍÒÓÔỒỔỖỘƠỜỞỠỢÙÚŨỤƯỪỬỮỰỲÝỸỶỴ)│
│  2. So khớp với evidence + catalog (cache 5 phút)    │
│  3. Fuzzy match: difflib threshold 0.92               │
│  4. Substring match: "Vay Tieu Dung" match            │
│     "Vay Tieu Dung - Momo Widget"                    │
│  5. Missing caveats: WARN (không BLOCK)              │
│  Regex fix: first letter [_VI_UPPER] thay [A-Z]      │
│     để nhận tên riêng Việt hoa dấu (Ề, Ỹ, Ậ...)      │
│     mà không match lowercase Việt (ị, ạ, ậ)          │
│  Tất định · ~1ms · 0 LLM call · severity=BLOCK       │
└───────────────────────────────────────────────────────┘
    │
    ▼
┌─ L4: Stats Guard (stats_guard.py) ──────────────────D┐
│  1. Comparative marker ("cao hơn", "thấp hơn")       │
│     → chỉ cho phép khi có significant comparison      │
│     → VI PHẠM → severity=BLOCK                       │
│  2. Causal marker ("vì", "do", "dẫn đến")            │
│     → chỉ cho phép khi có correlation phrase          │
│     → VI PHẠM → severity=BLOCK                       │
│     → word boundary: "do" không match "Doanh"        │
│  3. Correlation phrases mở rộng: "phân phối",        │
│     "lệch", "trung bình", "trung vị", "cỡ mẫu"       │
│  4. Skew guard: |mean - median|/|mean| > 0.3         │
│     → text phải nhắc median + negative_share         │
│     → severity=WARN (caveat, không chặn)             │
│  5. Sample size: n < 30 → INSUFFICIENT_SAMPLE        │
│     → severity=WARN (caveat, không chặn)             │
│  Tất định · ~10ms · 0 LLM call                       │
│  severity=BLOCK (unsupported/causal) | WARN (skew/n) │
└───────────────────────────────────────────────────────┘
    │
    ▼
┌─ L6: Trust Score + Decision (pipeline.py) ──────────┐
│  Aggregate L0-L5 → TrustScore:                        │
│  - Hard fail (severity=BLOCK + not passed) → 0.0     │
│  - Weighted sum:                                      │
│    schema 0.15 + numeric 0.25 + entity 0.10          │
│    + stats 0.20 + judge 0.20 + consistency 0.10      │
│  - Band: PASS ≥ 0.85 | HEDGE ≥ 0.60 | ABSTAIN < 0.60 │
│  Tất định · ~1ms · 0 LLM call                        │
└───────────────────────────────────────────────────────┘
    │
    ▼
┌─ L5: LLM Judge (judge.py) — ASYNC ──────────────────┐
│  Chạy SAU done, trên cùng SSE connection.             │
│  temperature=0, max_tokens=200.                       │
│  Trả: SUPPORTED / CONTRADICTED / NOT_ENOUGH_INFO      │
│  - contradiction_rate > 0 → BLOCK (hard fail)         │
│  - neutral_rate > 0.3 → WARN (contributes to HEDGE)   │
│  - entailment_rate ≥ 0.9 → PASS                       │
│  Bất đồng bộ · 1 LLM call                             │
│  severity=BLOCK (contradiction) | WARN (neutral)      │
└───────────────────────────────────────────────────────┘
    │
    ▼
┌─ L7: Policy Enforcement (gateway) ──────────────────┐
│  Khi agent dùng Resource Gateway (MCP):               │
│  tools/call → evaluate against Policy Group           │
│  Deny = tool không gọi = không có fact → L2 chặn      │
│  tools/list luôn allowed (bypass)                     │
│  Tất định · ~1ms · 0 LLM call                        │
└───────────────────────────────────────────────────────┘
```

---

## Tag Substitution (Frontend)

Sau khi LLM stream token, frontend thay thẻ `{{fact_id.row.col}}` bằng giá trị format vi-VN:

```javascript
function substituteTags(text, tagMap) {
  // 1. Exact match: {{F1.r1.romi}} → tagMap["F1.r1.romi"]
  // 2. Fuzzy match: {{F3.r1.neg_ratio}} → tìm tag giống trong tagMap
  //    - Match fact_id + column ending
  //    - Match fact_id + column containing
  // 3. No match → "—" (ẩn tag, không hiện nguyên văn)
}
```

Server gửi `tag_map` trong SSE event `evidence`:
```json
{
  "F1.r1.romi": "6,20",
  "F4.r1.profit": "392.498.488 VND",
  "F7.r1.negative_share": "52,0%"
}
```

---

## Auto-Tag (Post-hoc Grounding)

LLM thường viết số trực tiếp thay vì dùng thẻ. Auto-tag sửa điều này:

```python
def _auto_tag_numbers(text, evidence, tol=0.02):
    # 1. Build index: [(value, tag), ...] từ tất cả evidence facts
    # 2. Regex quét bare numbers (xem _BARE_NUM_RE bên dưới)
    # 3. _parse_vi_number: chuẩn hoá định dạng Việt/Anh → float
    # 4. Cho mỗi number, thu thập tất cả evidence values trong tol
    # 5. Disambiguation:
    #    - 0 candidates → skip (không tag)
    #    - 1 candidate  → tag
    #    - 2+ candidates → chỉ tag nếu best_diff < 0.5 × second_diff
    #      (best rõ ràng hơn thứ nhì); ngược lại skip (tránh mis-tag)
    # 6. Skip allowlist: 0, 1, 2, 100, 2000-2100, 95, 90, 99, 80, 75
```

**Regex**: `_BARE_NUM_RE = r"(?<![\w{}])(-?\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|-?\d+(?:[.,]\d+)?)(?![\w}])"`
- Match số lớn không có separator: `17529774.7317` ✅
- Match định dạng Việt: `6,20` (comma=decimal) ✅, `392.498.488` (dot=thousands) ✅
- Match định dạng Anh: `6.20` (dot=decimal) ✅, `392,498,488` (comma=thousands) ✅
- Không match bên trong `{{...}}` tags
- Không match số trong text/word

**Chuẩn hoá số Việt** (`_parse_vi_number`):
- Cả `.` và `,` → ký tự cuối cùng là decimal, kia là thousands
- Chỉ `,` + 1-2 chữ số sau → comma=decimal (`6,20` → 6.20)
- Chỉ `,` + 3+ chữ số sau → comma=thousands (`392,498` → 392498)
- Chỉ `.` + nhiều phần → dot=thousands (`392.498.488` → 392498488)

**Disambiguation** (tránh false confidence):
- Thu thập tất cả evidence values trong tolerance (2%)
- 0 candidates → skip (không tag)
- 1 candidate → tag
- 2+ candidates → chỉ tag nếu best_diff < 0.5 × second_diff (best rõ ràng hơn thứ nhì); ngược lại skip
- Không có exact-ish shortcut → mọi candidate được đối xử thống qua tolerance

---

## Decimal Handling

DB PostgreSQL trả `Decimal` cho numeric columns. Xử ở 3 chỗ:

| File | Fix |
|---|---|
| `numeric.py::_matches_policy` | `isinstance(v, Decimal) → float(v)` trước khi so sánh |
| `contracts.py::_format_value` | `isinstance(v, Decimal) → float(v)` trước khi format |
| `streaming.py::_build_evidence_index` | `float(val)` (đã handle Decimal) |

---

## Narrator Prompt

Prompt liệt kê **tất cả tag khả dụng** để LLM dùng chính xác, kèm **nguyên tắc thống kê** phòng thủ:

```
DANH SÁCH THẺ PHÉP DÙNG (copy chính xác, không đổi tên cột):
  {{F1.r1.romi}}
  {{F1.r2.romi}}
  {{F4.r1.profit}}
  ...

TUYỆT ĐỐI KHÔNG:
  - Viết chữ số trực tiếp (sai: 'ROMI 6,20' | đúng: 'ROMI {{F1.r1.romi}}')
  - Đổi tên cột (sai: 'F3.r1.neg_ratio' | đúng: 'F7.r1.negative_share')
  - Dùng fact_id không có trong danh sách

NGUYÊN TẮC THỐNG KÊ (tuân thủ nghiêm ngặt):
  - Không kết luận "A cao hơn/thấp hơn B" nếu EVIDENCE không ghi significant=true.
    Dùng rào đón: "có vẻ", "có xu hướng", "chưa đủ cơ sở".
  - Không dùng ngôn ngữ nhân quả ("vì", "do", "dẫn đến") nếu không có bằng chứng tương quan.
  - Nếu phân phối lệch, LUÔN kèm trung vị và tỷ lệ âm, không chỉ dùng trung bình.
  - Nếu cỡ mẫu n < 30, cảnh báo rõ "mẫu nhỏ, kết luận hạn chế".
  - Không ngoại suy tuyến tính từ dữ liệu lệch.
```

Prompt system (`narrate_campaign.yaml`, `narrate_persona.yaml`, `narrate_actions.yaml`)
cũng lặp lại các nguyên tắc này để **defense-in-depth**: ngay cả khi LLM bỏ qua reminder,
L4 (BLOCK) và L5 (BLOCK) vẫn chặn được ở tầng verify.

---

## Streaming Verification

**Token streaming** (không theo khối):
1. SSE `event: draft` → frontend hiện badge "Bản nháp — chưa kiểm chứng"
2. LLM stream token trực tiếp → SSE `event: token`
3. Frontend append token → `substituteTags()` → `renderMarkdown()` real-time
4. Stream xong → auto-tag + verify (L2+L3+L4) trên full text
5. SSE `event: verified` → trust badge thay thế draft badge

**Khi BLOCKED — replace-in-place**:
- Attempt 1 BLOCKED → SSE `event: replace` (reason=blocked, attempt=2)
  → frontend **xoá text cũ**, stream lại từ đầu (attempt 2)
- Attempt 2 vẫn BLOCKED → SSE `event: replace` (reason=abstain)
  → frontend thay text bằng **bảng số thô** (degraded_answer), badge ⚪ ABSTAIN
- Không bao giờ lặp quá 2 lần (config: `max_regen_attempts: 2`)

**UX contract**:
- Trong giai đoạn draft, số hiện dưới dạng thẻ `{{...}}` hoặc giá trị thay thế
  nhưng có visual cue (badge/hover) báo "chưa kiểm chứng"
- Khi `replace` event đến, frontend **ẩn ngay** text cũ → user không tiếp tục đọc bản sai
- Sau `verified`, badge chuyển sang 🟢/🟡/⚪ — text trở thành "đã kiểm chứng"

**Ưu điểm**: UX mượt, user thấy text chảy real-time, không bị cắt khối mất ngữ cảnh.
**Trade-off**: Verification chạy cuối, nhưng draft badge + replace-in-place đảm bảo
user không bị lừa đọc bản sai mà tưởng đã kiểm chứng.

---

## Trust Score Bands

| Band | Huy hiệu | UI | Điều kiện |
|---|---|---|---|
| PASS | 🟢 Đã kiểm chứng | Response đầy đủ | value ≥ 0.85 |
| HEDGE | 🟡 Hạn chế tin cậy | Response + rào đón | 0.60 ≤ value < 0.85 |
| ABSTAIN | ⚪ Từ chối | Chỉ bảng số thô | value < 0.60 hoặc max_regen_exceeded |
| BLOCKED | 🔴 Bị chặn | Sinh lại (tối đa 2 lần) | hard fail (BLOCK + not passed) |

**Fallback chain khi BLOCKED**:
1. Attempt 1 → BLOCKED → regenerate (attempt 2)
2. Attempt 2 → BLOCKED → **ABSTAIN** (bảng số thô, không narrative)
3. Không bao giờ lặp vô hạn. Log warning cho mỗi lần fail.
4. Judge (L5) bị skip khi ABSTAIN (không tốn thêm LLM call).

---

## Danh mục lỗi bắt được

| # | Kiểu lỗi | Ví dụ | Lớp bắt | Severity |
|---|---|---|---|---|
| H1 | Bịa số | "ROMI = 2,4" (thật: 1,31) | L2 + Auto-tag | BLOCK |
| H2 | Trích sai số | Lấy `net_profit` dòng khác | L2 | BLOCK |
| H3 | Lẫn đơn vị | "6,2%" cho ROMI 6,20 lần | L2 (policy) | BLOCK |
| H4 | Bịa tên | "chiến dịch Instagram Stories" | L3 | BLOCK |
| H5 | So sánh trên nhiễu | "Freelancer sinh lời nhất" | L4 | **BLOCK** |
| H6 | Mẫu quá nhỏ | Kết luận từ n=29 | L4 | WARN (caveat) |
| H7 | Suy nhân quả | "Cài app làm tăng lợi nhuận" | L4 + L5 | **BLOCK** |
| H8 | Bỏ caveat | Nêu trung bình mà không nói median | L3 (WARN) | WARN |
| H9 | Bịa cột SQL | `fact_loan.campaign_id` | L0 | BLOCK |
| H10 | Sai mẫu số | `SUM/COUNT(*)` gồm hồ sơ bị từ chối | Semantic layer | — |
| H11 | Ngoại suy thời gian | "So sánh tháng 8 vs tháng 7" | DQ-03 + L4 | WARN |
| H12 | Diễn giải bảng rỗng | "Doanh thu tăng 12%" khi không có dòng | L2 + L6 | BLOCK |
| H13 | Lạc đề | Trả lời chuyện không được hỏi | L5 | **BLOCK** |
| H14 | Đọc ngược dấu | Gọi ROMI −1,85 là "hiệu quả" | L5 | **BLOCK** |
| H15 | Trung bình che cơ cấu | "TB 199k" mà không nói median −86k | L4 skew guard | WARN |
| H16 | Ngoại suy tuyến tính | "1000 khách ≈ 200 triệu" | L4 skew guard | WARN |
| H17 | Hallucinate fact_id | `{{F2_1.r1.romi}}` | Tag repair + L2 | BLOCK |
| H18 | Viết số thẳng | "ROMI 6,20" thay vì thẻ | L2 (bare number) + Auto-tag | BLOCK |
| H19 | Bịa tên cột | `{{F3.r1.neg_ratio}}` | Prompt + Frontend fuzzy match | — |
| H20 | Decimal không match | DB trả Decimal, L2 skip | `isinstance(Decimal) → float` | — |
| H21 | Số Việt không match | "6,20" không match regex Anh | `_parse_vi_number` + regex mở rộng | — |
| H22 | Auto-tag gán nhầm | Hai fact gần nhau, tag sai nguồn | Disambiguation (skip nếu ambiguous) | — |

---

## Config (`config/verify.yaml`)

```yaml
weights:
  schema: 0.15      # L0
  numeric: 0.25     # L2 (quan trọng nhất)
  entity: 0.10      # L3
  stats: 0.20       # L4 (BLOCK cho unsupported/causal, WARN cho skew/n)
  judge: 0.20       # L5 (BLOCK cho contradiction, WARN cho neutral)
  consistency: 0.10 # self-consistency (freeform only)

thresholds:
  t_high: 0.85      # PASS
  t_low: 0.60       # HEDGE

alpha: 0.05
min_effect_size: 0.2
min_sample_size: 30
max_regen_attempts: 2  # sau 2 lần BLOCK → ABSTAIN (bảng thô)

numeric:
  allowlist:
    years: { min: 2000, max: 2100 }
    ordinals: { min: 1, max: 10 }
    literals: [0, 1, 2, 100]
    percentages: [95, 90, 99, 80, 75]  # auto-tag skip
```

**Lớp BLOCK (hard fail → 0.0)**: L2 numeric, L3 entity, L4 unsupported/causal,
L5 contradiction.
**Lớp WARN (contributes to score)**: L4 skew/sample-size, L5 neutral, L8 caveats.

---

## File Map

| File | Lớp | Vai trò |
|---|---|---|
| `app/data/sqlguard.py` | L0, L1 | SQL AST + EXPLAIN (ready for freeform SQL) |
| `app/verify/numeric.py` | L2 | Numeric grounding (PCN) + `parse_vi_number` |
| `app/verify/entity.py` | L3 | Entity grounding |
| `app/verify/stats_guard.py` | L4 | Stats + skew guard (BLOCK/WARN) |
| `app/verify/judge.py` | L5 | LLM judge (async, BLOCK/WARN) |
| `app/verify/pipeline.py` | L6 | Trust score + `run_sync_checks` (L0-L4 + consistency) |
| `app/verify/consistency.py` | — | Self-consistency (ready for multi-sample) |
| `app/verify/vi_text.py` | — | Vietnamese NLP + `_VI_UPPER` regex |
| `app/verify/config.py` | — | Load verify.yaml |
| `app/agent/streaming.py` | — | Auto-tag + tag repair (uses `parse_vi_number` from numeric) |
| `app/agent/narrator.py` | — | Prompt + tag list + thống kê reminder |
| `app/agent/orchestrator.py` | — | Fallback chain (max 2 → ABSTAIN) |

**Removed (dead code)**: `stages.py`, `tools/`, `clv.py`, `segments.py`,
`memory/tools.py`, `semantic/entities.py`, `verify/models.py`.

---

## SSE Event Contract (Frontend)

| Event | Data | Khi nào | Frontend action |
|---|---|---|---|
| `draft` | `{status, attempt}` | Trước token stream | Hiện badge "Bản nháp" |
| `token` | `{text}` | Mỗi token | Append text, substitute tags |
| `replace` | `{reason, attempt?}` | BLOCKED → regen | **Xoá text cũ**, stream lại |
| `replace` | `{reason: "abstain", md}` | Max attempts | Thay bằng bảng thô |
| `verified` | `{trust, band, checks}` | Sau verify | Thay badge, hiện trust score |
| `done` | `{trace_id, decision}` | Hoàn tất | Lock text, ẩn draft badge |
| `judge` | `{entailment, contradiction}` | Sau L5 | Cập nhật trust nếu contradiction |

---

## Kết quả thực tế

Trước fix: trust = 0.000 BLOCKED 🔴 (mọi câu hỏi bị chặn)
Sau fix: trust = 0.978 PASS 🟢

| Fix | Vấn đề | Giải pháp |
|---|---|---|
| Decimal handling | DB trả Decimal, L2 `isinstance(v, (int,float))` skip | `isinstance(v, Decimal) → float(v)` |
| Regex entity | `[A-ZÀ-Ỹ]` match lowercase Việt (ị, ạ) | `[_VI_UPPER]` = A-Z + chữ hoa Việt có dấu |
| % thống kê | "95%" bị bắt là bare number | Allowlist 95, 90, 99, 80, 75 |
| Causal false positive | "Do phân phối lệch..." bị flag | Thêm thuật ngữ thống kê vào exception |
| Missing caveats BLOCK | Caveat không nhắc nguyên văn → BLOCK | Đổi thành WARN |
| Auto-tag regex | Không match số lớn không separator | Regex mở rộng + `_parse_vi_number` |
| Tag unresolved | `{{F3.r1.neg_ratio}}` hiện nguyên văn | Frontend fuzzy match + "—" |
| LLM bịa tên cột | `neg_ratio` thay vì `negative_share` | Prompt liệt kê tag + ví dụ sai/đúng |
| L5 severity mâu thuẫn | Judge ghi WARN nhưng logic nói BLOCK | severity=BLOCK cho contradiction, WARN cho neutral |
| L4 severity yếu | So sánh nhiễu/nhân quả chỉ WARN | BLOCK cho unsupported + causal, WARN cho skew/n |
| Auto-tag mis-tag | Hai fact gần nhau → gán nhầm tag | Disambiguation: skip nếu ambiguous |
| Số Việt không match | "6,20" không match regex Anh | `_parse_vi_number` + regex nhận cả `.` và `,` |
| Streaming UX | User đọc bản sai trước verify | Draft badge + replace-in-place khi BLOCK |
| Fallback không rõ | BLOCKED lần 2 vẫn lặp | Max 2 attempts → ABSTAIN (bảng thô) |
| Prompt thiếu quy tắc TK | LLM suy nhân quả, so sánh nhiễu | Nguyên tắc thống kê trong prompt + reminder |
| Marker false positive | "Doanh thu" match causal "do" | Word boundary `(?<!\w)do(?!\w)` trong has_marker |
| NUM_RE split năm | "2026" bị tách thành "202"+"6" | `(?:[.\s]\d{3})+` yêu cầu ≥1 separator |
| Streaming cut sai | rfind cắt ở marker cuối, 1 block thay vì 2 | find earliest + `len(marker)` |
