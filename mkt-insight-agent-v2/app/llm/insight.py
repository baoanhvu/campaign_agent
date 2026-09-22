"""LLM insight for dashboard — Python computes numbers, LLM only interprets.

This is SEPARATE from the chat agent pipeline. Dashboard insights are displayed
directly without anti-hallucination verification (Hướng A). The raw numbers are
always visible in tables/charts for cross-checking.

Ported from reference repo's llm_insight.py, adapted to use existing LLMClient.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

from app.logging_ import get_logger

_log = get_logger("llm.insight")

SYSTEM_PROMPT = """Bạn là chuyên gia phân tích marketing/kinh doanh cho sản phẩm vay tiêu dùng (Lending) tại 1 ngân hàng.
Người đọc báo cáo là CẤP QUẢN LÝ/CEO và các team Marketing/Sale — KHÔNG PHẢI Data Analyst. Hãy viết như đang báo cáo trực tiếp cho lãnh đạo: ngắn gọn, nói thẳng ý nghĩa kinh doanh và việc cần làm.

Bạn được cung cấp CÁC CON SỐ ĐÃ ĐƯỢC TÍNH SẴN cho MỘT loại sản phẩm cụ thể (First Loan hoặc Re-loan) trong ngày hôm nay. Mỗi con số hôm nay được so với "mức bình thường" của chính kênh đó — tức trung bình 7 ngày gần nhất (không tính hôm nay). Gọi là "mức bình thường" hoặc "trung bình 7 ngày gần nhất", KHÔNG gọi là "ngưỡng cảnh báo" hay "baseline".

NHIỆM VỤ: chỉ DIỄN GIẢI các con số này thành insight có logic nhân-quả và đề xuất hành động cụ thể — bao gồm cả hành động KHẮC PHỤC vấn đề lẫn hành động CHỦ ĐỘNG THÚC ĐẨY tăng trưởng khoản vay.

QUY TẮC BẮT BUỘC:
- KHÔNG tự tính toán hoặc suy đoán ra bất kỳ con số nào ngoài những gì đã được cung cấp. Khi cần nói mức chênh lệch, dùng đúng % có sẵn trong trường "phan_tram_chenh_lech".
- Trong "diem_nghen": liệt kê các điểm nghẽn đáng chú ý nhất (tối đa 5). Trường "nguyen_nhan_kha_di" là TÙY CHỌN — CHỈ điền khi thực sự có cơ sở hợp lý; nếu KHÔNG có cơ sở rõ ràng thì để null.
- CHỈ nói một chỉ số "tăng" hoặc "giảm" so với mức bình thường khi chỉ số đó có trong "cac_diem_dang_chu_y".
- Khi so sánh giữa các kênh ("cao nhất", "thấp nhất"), CHỈ dùng đúng kết quả trong "so_sanh_giua_cac_kenh".
- Agent chỉ PHÂN TÍCH và ĐỀ XUẤT - không được viết như thể agent sẽ tự động thực hiện hành động nào.
- Trả lời bằng tiếng Việt CÓ DẤU đầy đủ, ngắn gọn, rõ ràng.
- Các trường dạng danh sách (insight_marketing, insight_sale): mỗi phần tử là 1 CÂU NGẮN.
- Trong "suggestions", bắt buộc có ít nhất 1 đề xuất mang tính THÚC ĐẨY TĂNG TRƯỞNG nếu số liệu cho phép.
- Mỗi suggestion phải gắn đúng "team" (Marketing, Sale, hoặc "Ca hai").
- Trả về DUY NHẤT 1 JSON object đúng định dạng, không thêm text nào khác ngoài JSON.

QUY TẮC NGÔN NGỮ:
- TUYỆT ĐỐI KHÔNG dùng thuật ngữ thống kê: "độ lệch chuẩn", "SD", "sigma", "z-score", "baseline".
- KHÔNG dùng "critical"/"warning" bằng tiếng Anh. Dùng "cần lưu ý" hoặc "cần chú ý".
- KHÔNG chép tên trường dữ liệu kỹ thuật vào câu văn.

QUY TẮC VỀ CHI PHÍ:
- CPL/CPA TĂNG không tự động là xấu. Phải đối chiếu doanh số giải ngân trước khi kết luận.
- Chi phí tăng mà doanh số tăng tương xứng → tích cực. Chi phí tăng nhưng doanh số không tăng → kém hiệu quả.
"""

OUTPUT_SCHEMA = """{
  "tong_quan": "2-3 câu tóm tắt sức khoẻ chung, ngôn ngữ kinh doanh",
  "diem_nghen": [{"campaign_name": "...", "kpi_label": "...", "mo_ta": "... (dùng % chênh lệch)", "nguyen_nhan_kha_di": "... hoặc null"}],
  "hieu_qua_chi_phi": "nhận xét về CPL/CPA, LUÔN đối chiếu doanh số trước khi kết luận",
  "insight_marketing": ["1 ý ngắn cho Marketing", "ý tiếp theo"],
  "insight_sale": ["1 ý ngắn cho Sale"],
  "suggestions": [{"noi_dung": "...", "uu_tien": "cao|trung_binh|thap", "team": "Marketing|Sale|Ca hai"}],
  "critical_highlights": [{"campaign_name": "...", "insight_1_cau": "...", "de_xuat_1_cau": "..."}]
}"""

FALLBACK_RESULT = {
    "tong_quan": "Chưa có insight (LLM chưa được cấu hình). Xem số liệu thô bên dưới.",
    "diem_nghen": [],
    "hieu_qua_chi_phi": None,
    "insight_marketing": [],
    "insight_sale": [],
    "suggestions": [],
    "critical_highlights": [],
}

_FUNNEL_COL_LABELS_VI = {
    "campaign_name": "kenh", "channel": "kenh_nhom", "product": "san_pham",
    "reach_count": "so_lead_tiep_can", "registered_count": "so_ho_so_dang_ky",
    "approved_count": "so_don_duoc_duyet", "disbursed_count": "so_don_giai_ngan",
    "settled_count": "so_khoan_tat_toan",
    "dropoff_reach_to_register": "ty_le_rot_tiep_can_den_dang_ky",
    "dropoff_register_to_approve": "ty_le_rot_dang_ky_den_duyet",
    "cpl": "chi_phi_moi_lead", "cpa": "chi_phi_moi_don_giai_ngan",
    "cac": "cac_chi_phi_thu_hut_moi_khoan_giai_ngan",
    "avg_loan_value": "gia_tri_khoan_vay_trung_binh",
    "roi_outstanding": "loi_nhuan_lai_tren_du_no",
    "ad_spend": "chi_phi_lead", "disbursed_amount": "doanh_so_giai_ngan",
    "cost_to_disbursed_ratio": "ty_le_chi_phi_tren_doanh_so",
    "avg_reloan_cadence_days": "chu_ky_vay_lai_ngay",
    "install_count": "so_luot_cai_app", "phone_verified_count": "so_xac_thuc_sdt",
}

LEVEL_LABEL_VI = {"critical": "can_luu_y", "warning": "can_chu_y"}


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            text = brace.group(0)
    return json.loads(text)


def _pct_diff(value, baseline):
    try:
        if baseline is None or value is None or baseline == 0:
            return None
        if isinstance(baseline, float) and math.isnan(baseline):
            return None
        return round((value - baseline) / baseline * 100, 1)
    except (TypeError, ZeroDivisionError):
        return None


def _build_prompt(as_of_date: str, product: str, today_rows: list[dict],
                  anomalies: list[dict], contributions: dict) -> str:
    funnel_renamed = []
    for r in today_rows:
        row = {}
        for k, v in r.items():
            row[_FUNNEL_COL_LABELS_VI.get(k, k)] = v
        funnel_renamed.append(row)

    comparison = {}
    if len(today_rows) >= 2:
        for col in ["cpl", "disbursed_amount"]:
            vals = [(r.get("campaign_name"), r.get(col)) for r in today_rows if r.get(col) is not None]
            if len(vals) >= 2:
                vals.sort(key=lambda x: x[1], reverse=True)
                comparison[f"kenh_{col}_cao_nhat"] = vals[0][0]
                comparison[f"kenh_{col}_thap_nhat"] = vals[-1][0]

    flagged = [a for a in anomalies if a["level"] in ("warning", "critical")]
    anomaly_records = []
    for a in flagged:
        anomaly_records.append({
            "kenh": a["campaign_name"],
            "kpi": a["kpi_label"],
            "loai_kpi": a["kpi_type"],
            "gia_tri_hom_nay": a["value"],
            "muc_binh_thuong_7_ngay_gan_nhat": a["baseline_mean"],
            "phan_tram_chenh_lech": _pct_diff(a["value"], a["baseline_mean"]),
            "muc_do": LEVEL_LABEL_VI.get(a["level"], a["level"]),
        })

    contrib_payload = {}
    for col, data in contributions.items():
        contrib_payload[data["label"]] = {
            "tong_hom_nay": data["tong_hom_nay"],
            "tong_trung_binh_7_ngay": data["tong_tb_7_ngay"],
            "tong_thay_doi": data["tong_thay_doi"],
            "phan_tram_thay_doi": data["tong_thay_doi_pct"],
            "theo_kenh": [
                {"kenh": r["campaign_name"], "thay_doi": r["thay_doi"], "ty_trong_dong_gop_pct": r["ty_trong_pct"]}
                for r in data["theo_kenh"]
            ],
        }

    payload = {
        "ngay": as_of_date,
        "san_pham": product,
        "funnel_hom_nay_theo_kenh": funnel_renamed,
        "so_sanh_giua_cac_kenh": comparison,
        "cac_diem_dang_chu_y": anomaly_records,
    }
    if contrib_payload:
        payload["dong_gop_vao_bien_dong_so_voi_tb_7_ngay"] = contrib_payload

    return (
        f"Dữ liệu đã tính sẵn hôm nay cho sản phẩm '{product}' (JSON):\n"
        + json.dumps(payload, ensure_ascii=False, default=str, indent=2)
        + "\n\nHãy trả về insight theo ĐÚNG schema JSON sau:\n"
        + OUTPUT_SCHEMA
    )


async def interpret_daily(as_of_date: str, product: str, today_rows: list[dict],
                          anomalies: list[dict], contributions: dict) -> dict:
    """Call LLM to interpret pre-computed numbers for one product.

    Returns structured JSON for dashboard display. Falls back to FALLBACK_RESULT
    if LLM is not configured or fails.
    """
    try:
        from app.llm.client import get_client
        client = get_client()
    except Exception:
        return dict(FALLBACK_RESULT)

    prompt = _build_prompt(as_of_date, product, today_rows, anomalies, contributions)
    try:
        response = await client.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=2000,
        )
        return _extract_json(response)
    except Exception as exc:
        _log.warning("LLM insight failed for %s: %s", product, exc)
        result = dict(FALLBACK_RESULT)
        result["tong_quan"] = f"LLM lỗi: {exc}. Xem số liệu thô bên dưới."
        return result
