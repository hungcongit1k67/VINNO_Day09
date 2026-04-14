# Báo Cáo Cá Nhân — Lab Day 09

**Họ tên:** Bùi Đức Tiến
**Ngày:** 2026-04-14
**Vai trò:** Trace & Docs Owner (Sprint 4)

---

## 1. Phần tôi phụ trách

Tôi phụ trách **Sprint 4 — Trace, Evaluation, Documentation**:

**eval_trace.py:**
- Chạy pipeline với 15 test questions, lưu trace từng câu vào `artifacts/traces/`
- Implement `analyze_traces()` — đọc trace, tính metrics: routing_distribution, avg_confidence, avg_latency_ms, mcp_usage_rate, hitl_rate, top_sources
- Implement `compare_single_vs_multi()` — so sánh Day 08 vs Day 09 theo 4 metrics
- Fix lỗi encoding UTF-8 khi đọc trace files trên Windows

**Tài liệu kỹ thuật:**
- `docs/system_architecture.md` — mô tả kiến trúc, ASCII diagram pipeline, vai trò từng worker, lý do chọn multi-agent
- `docs/routing_decisions.md` — ghi lại 5 quyết định routing thực tế từ trace (không phải giả định)
- `docs/single_vs_multi_comparison.md` — so sánh 4 metrics có số liệu thực tế

**Báo cáo:**
- `reports/group_report.md` — tổng hợp kết quả nhóm
- `reports/individual/BuiDucTien.md` — file này

**Kết quả trace sau 15 test questions:**

| Metric | Giá trị |
|--------|---------|
| Thành công | 15/15 |
| avg confidence | 0.644 |
| avg latency (warm) | ~20 ms |
| routing: retrieval_worker | 8/15 (53%) |
| routing: policy_tool_worker | 7/15 (46%) |
| HITL triggered | 1/15 (q09) |
| MCP tool calls | 3 queries |
| Docs covered | 5/5 tài liệu |

---

## 2. Một quyết định kỹ thuật tôi đề xuất

**Quyết định: Trace format JSON-per-file thay vì một file JSONL duy nhất cho test questions**

Trong thiết kế `eval_trace.py`, tôi có hai lựa chọn lưu trace:

**Option A (JSONL tất cả trong một file):**
```python
# Tất cả 15 câu gộp vào artifacts/traces/all_traces.jsonl
with open("artifacts/traces/all_traces.jsonl", "a") as f:
    f.write(json.dumps(state) + "\n")
```

**Option B (JSON-per-file — tôi chọn):**
```python
# Mỗi câu = một file .json riêng với run_id
filename = f"artifacts/traces/{state['run_id']}.json"
with open(filename, "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)
```

**Lý do chọn Option B:**
1. **Debug từng câu dễ hơn:** Khi q09 (ERR-403-AUTH) có confidence 0.43, tôi mở đúng file trace của câu đó để kiểm tra `history` và `retrieved_chunks`, không cần parse toàn bộ JSONL.
2. **Phân tích linh hoạt hơn:** `analyze_traces()` đọc tất cả file trong `artifacts/traces/`, có thể thêm/xóa từng trace mà không ảnh hưởng nhau.
3. **Human-readable:** File JSON indent=2 dễ đọc hơn JSONL khi debug thủ công.
4. **Grading format vẫn đúng:** File `artifacts/grading_run.jsonl` (cho chấm điểm) vẫn theo format JSONL như yêu cầu — hai format phục vụ hai mục đích khác nhau.

**Evidence từ trace thực tế:**

Nhờ format này, tôi phát hiện được:
- q09 trace: `"hitl_triggered": true` và `"confidence": 0.43` → xác nhận pipeline abstain đúng, không hallucinate
- q15 trace: `"retrieved_sources": ["access_control_sop.txt", "sla_p1_2026.txt"]` → xác nhận cross-doc retrieval thành công cho multi-hop query

**Trade-off:** Tạo ra nhiều file nhỏ (15 files) thay vì 1 file. Nhưng với scale lab (15–100 câu), đây không phải vấn đề.

---

## 3. Một lỗi đã sửa

**Lỗi: UnicodeDecodeError khi `analyze_traces()` đọc trace files trên Windows**

**Mô tả lỗi:**

Sau khi 15/15 test questions chạy thành công, `eval_trace.py` crash khi gọi `analyze_traces()`:

```
UnicodeDecodeError: 'charmap' codec can't decode byte 0x90 in position 274:
character maps to <undefined>
```

**Root cause:**

```python
# Code cũ trong analyze_traces():
with open(os.path.join(traces_dir, fname)) as f:   # <-- BUG: dùng encoding mặc định cp1252
    traces.append(json.load(f))
```

Trên Windows, encoding mặc định của `open()` là `cp1252` (Windows Western European). Trace files lưu bằng `json.dump(..., ensure_ascii=False)` chứa ký tự tiếng Việt (UTF-8). Khi `analyze_traces()` cố đọc lại bằng `cp1252`, một số byte UTF-8 (như `0x90`) không có trong bảng mã cp1252 → crash.

**Cách sửa:**

```python
# Code mới:
with open(os.path.join(traces_dir, fname), encoding="utf-8") as f:   # Fixed
    traces.append(json.load(f))
```

**Bằng chứng trước/sau:**

| | Trước fix | Sau fix |
|-|-----------|---------|
| `analyze_traces()` | Crash: UnicodeDecodeError | Thành công |
| Metrics output | Không có | routing_distribution, avg_confidence, top_sources... |
| `compare_single_vs_multi()` | Không chạy đến | Tạo được `artifacts/eval_report.json` |

**Lý do lỗi không phát hiện ngay:**

Pipeline chạy và lưu trace dùng `encoding="utf-8"` (đúng), nhưng `analyze_traces()` đọc lại thiếu encoding. Lỗi chỉ xuất hiện ở bước *phân tích trace*, không phải ở bước *ghi trace* — nên không bị phát hiện ngay khi viết code.

---

## 4. Tự đánh giá

**Làm tốt:**
- Trace format đầy đủ 100% fields theo yêu cầu: `run_id`, `task`, `supervisor_route`, `route_reason`, `workers_called`, `mcp_tools_used`, `retrieved_sources`, `final_answer`, `confidence`, `hitl_triggered`, `latency_ms`
- Điền đầy đủ 3 docs templates với số liệu thực tế từ trace (không phải giả định)
- `routing_decisions.md` có 5 quyết định routing thực tế, mỗi cái đều có task đầu vào, route, route_reason, và kết quả
- `single_vs_multi_comparison.md` so sánh 4 metrics với con số cụ thể (0.644 confidence, ~20ms latency, v.v.)
- Phát hiện và ghi lại lỗi encoding đúng quy trình: mô tả → root cause → fix → bằng chứng

**Còn yếu:**
- Một số trace có answer format thô (extractive), khó đọc hơn LLM synthesis — ảnh hưởng đến điểm grading

**Nhóm phụ thuộc vào tôi ở:**
- Trace files: nếu `eval_trace.py` crash, nhóm không có artifact để nộp
- Docs templates: hồ sơ kỹ thuật của nhóm phụ thuộc vào tôi điền đúng và đủ

---

## 5. Nếu có 2 giờ thêm, tôi sẽ làm gì

**Cải tiến: Thêm auto-grading script so sánh trace với expected answers**

Từ trace, tôi thấy `data/test_questions.json` có sẵn `expected_answer` và `expected_sources` cho mỗi câu, nhưng `eval_trace.py` hiện không so sánh chúng với output thực tế.

Nếu có 2 giờ thêm, tôi sẽ thêm vào `eval_trace.py`:

```python
def evaluate_answer_quality(result: dict, question: dict) -> dict:
    """
    So sánh answer với expected_answer bằng keyword matching.
    Kiểm tra retrieved_sources có chứa expected_sources không.
    """
    expected_srcs = set(question.get("expected_sources", []))
    actual_srcs = set(result.get("retrieved_sources", []))
    source_hit = expected_srcs.issubset(actual_srcs) if expected_srcs else True

    # Keyword check: expected_answer keywords trong final_answer?
    expected_kws = question.get("expected_answer", "").lower().split()[:5]
    answer_lower = result.get("final_answer", "").lower()
    kw_hit = sum(1 for kw in expected_kws if kw in answer_lower) / max(len(expected_kws), 1)

    return {
        "source_recall": source_hit,
        "keyword_hit_rate": round(kw_hit, 2),
        "confidence": result.get("confidence", 0),
    }
```

**Lý do cụ thể từ trace:**
- q06 (ticket P1 không phản hồi 10 phút): `retrieved_sources = ['sla_p1_2026.txt', 'it_helpdesk_faq.txt']`, `expected_sources = ['sla_p1_2026.txt']` — source_recall = True ✓
- q08 (5-step P1 process): `retrieved_sources = ['policy_refund_v4.txt']`, `expected_sources = ['sla_p1_2026.txt']` — source_recall = False ✗ → cần cải thiện retrieval

Script này cho phép nhóm tự chấm trước khi grading_questions.json được public — không phải "làm tốt hơn chung chung" mà là cải tiến có đo lường cụ thể.
