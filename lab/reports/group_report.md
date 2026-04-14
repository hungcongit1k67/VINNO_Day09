# Báo Cáo Nhóm — Lab Day 09: Multi-Agent Orchestration

**Tên nhóm:** Vinno
**Ngày:** 2026-04-14

| Tên | Vai trò | Sprint lead |
|-----|---------|------------|
| Nguyễn Công Hùng | Supervisor Owner | Sprint 1 |
| Chu Thành Thông | Worker Owner | Sprint 2 |
| Phùng Hữu Phú | MCP Owner | Sprint 3 |
| Bùi Đức Tiến | Trace & Docs Owner | Sprint 4 |

---

## 1. Tóm tắt hệ thống

Hệ thống trợ lý nội bộ CS + IT Helpdesk Day 09 sử dụng **Supervisor-Worker pattern** với:
- 1 Supervisor node (`graph.py`) quyết định routing dựa theo keyword
- 3 Workers: `retrieval_worker`, `policy_tool_worker`, `synthesis_worker`
- 1 MCP Server với 4 tools: `search_kb`, `get_ticket_info`, `check_access_permission`, `create_ticket`
- Embedding: Sentence Transformers `all-MiniLM-L6-v2` + ChromaDB (63 chunks từ 5 tài liệu)
- Synthesis: Extractive approach (grounded, không hallucinate khi không có API key)

**Kết quả chạy 15 test questions:**
- 15/15 thành công (0 crash)
- avg confidence: 0.644
- avg latency (warm): ~20 ms
- MCP tool calls: 3 queries (q03, q13, q15)
- HITL triggered: 1 lần (q09 — mã lỗi không rõ ERR-403-AUTH)

---

## 2. Phân công công việc

| Sprint | Thành phần | Người phụ trách | Trạng thái |
|--------|------------|-----------------|------------|
| Sprint 1 | `graph.py` — AgentState, supervisor_node, routing logic, build_graph | Nguyễn Công Hùng | Hoàn thành |
| Sprint 2 | `workers/retrieval.py` — ChromaDB dense retrieval, model cache | Chu Thành Thông | Hoàn thành |
| Sprint 2 | `workers/policy_tool.py` — exception detection, MCP integration | Chu Thành Thông | Hoàn thành |
| Sprint 2 | `workers/synthesis.py` — LLM chain + extractive fallback | Chu Thành Thông | Hoàn thành |
| Sprint 3 | `mcp_server.py` — 4 tools (search_kb, get_ticket_info, check_access_permission, create_ticket) | Phùng Hữu Phú | Hoàn thành |
| Sprint 3 | MCP integration trong `policy_tool.py` | Phùng Hữu Phú | Hoàn thành |
| Sprint 4 | `eval_trace.py` — chạy 15 câu, lưu trace, tính metrics | Bùi Đức Tiến | Hoàn thành |
| Sprint 4 | `docs/` — system_architecture, routing_decisions, single_vs_multi_comparison | Bùi Đức Tiến | Hoàn thành |
| Sprint 4 | `reports/group_report.md` và `reports/individual/` | Bùi Đức Tiến | Hoàn thành |

---

## 3. Quyết định kỹ thuật chính

### 3.1 Keyword-based routing thay vì LLM router (Nguyễn Công Hùng)
Supervisor dùng keyword matching để routing (không dùng LLM classifier). Lý do:
- Nhanh hơn (0 ms vs 500–2000 ms cho LLM call)
- Deterministic — dễ debug và explain
- Đủ chính xác cho bài toán này (15/15 route hợp lý)
- Trace có `route_reason` rõ ràng

### 3.2 Retrieval trước policy — không phải sau (Chu Thành Thông)
Graph chạy `retrieval → policy_tool → synthesis` thay vì `policy_tool (có MCP) → retrieval`. Lý do: đảm bảo policy_tool luôn có context đầu vào, giảm MCP `search_kb` call không cần thiết.

### 3.3 4 MCP tools với dispatch pattern (Phùng Hữu Phú)
MCP server expose 4 tools qua `dispatch_tool(tool_name, input)`. Policy worker không gọi ChromaDB trực tiếp mà gọi qua MCP client. Lý do: isolation, dễ swap sang HTTP server thật, có audit trail trong trace.

### 3.4 Trace format JSON-per-file + JSONL cho grading (Bùi Đức Tiến)
Mỗi câu hỏi lưu một file `.json` riêng trong `artifacts/traces/` thay vì gộp chung. Lý do: dễ debug từng câu, `analyze_traces()` đọc được từng trace độc lập. File `grading_run.jsonl` vẫn theo format JSONL như yêu cầu.

---

## 4. Kết quả grading questions (self-eval)

| ID | Câu hỏi tóm tắt | Route | MCP tools | Sources |
|----|-----------------|-------|-----------|---------|
| q01 | P1 22:47 ai nhận thông báo | retrieval_worker | — | sla_p1_2026.txt |
| q02 | Đơn 31/01 hoàn tiền 07/02 | policy_tool_worker | — | policy_refund_v4.txt |
| q03 | Level 3 bao nhiêu người phê duyệt | policy_tool_worker | check_access_permission | access_control_sop.txt |
| q04 | Store credit % | policy_tool_worker | — | policy_refund_v4.txt |
| q05 | P1 không phản hồi 10 phút | retrieval_worker | — | sla_p1_2026.txt |
| q07 | Mức phạt tài chính vi phạm SLA | retrieval_worker | — | abstain (không có trong docs) |
| q09 | P1 2am + Level 2 access | policy_tool_worker | check_access_permission, get_ticket_info | access_control_sop.txt, sla_p1_2026.txt |
| q10 | Flash Sale + lỗi nhà sản xuất | policy_tool_worker | — | policy_refund_v4.txt |

---

## 5. Bài học rút ra

1. **Routing granularity:** Phát hiện cần multi-hop detection khi cả 2 keyword types xuất hiện trong cùng task (e.g., q15: "P1 2am + Level 2 access").

2. **False positive policy:** `analyze_policy` cũ kiểm tra `context_text` cho flash_sale → false positive cho q02. Fix: chỉ check `task_lower` cho flash sale exception.

3. **Embedding warm-up:** Query đầu mất 15s load model. Fix: cache model tại module level, các query sau chỉ mất ~20ms.

4. **Abstain quan trọng hơn trả lời sai:** q09 (ERR-403-AUTH) không có trong docs → pipeline đúng nên abstain với confidence thấp (0.43), KHÔNG hallucinate.

5. **Encoding trên Windows:** `eval_trace.py` mặc định mở file với `cp1252` → crash khi đọc trace có tiếng Việt. Fix: thêm `encoding="utf-8"` vào `open()`.

---

## 6. Files nộp bài

| File | Người phụ trách | Trạng thái |
|------|-----------------|------------|
| `graph.py` | Nguyễn Công Hùng | Hoàn thành |
| `workers/*.py` | Chu Thành Thông | Hoàn thành |
| `mcp_server.py` | Phùng Hữu Phú | Hoàn thành |
| `contracts/worker_contracts.yaml` | Chu Thành Thông | Hoàn thành |
| `eval_trace.py` | Bùi Đức Tiến | Hoàn thành |
| `artifacts/traces/` (15 files) | Bùi Đức Tiến | Hoàn thành |
| `docs/*.md` | Bùi Đức Tiến | Hoàn thành |
| `reports/group_report.md` | Bùi Đức Tiến | File này |
| `reports/individual/BuiDucTien.md` | Bùi Đức Tiến | Hoàn thành |
