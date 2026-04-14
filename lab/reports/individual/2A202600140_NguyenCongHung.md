# Báo Cáo Cá Nhân — Lab Day 09

**Họ tên:** Nguyễn Công Hùng
**Ngày:** 2026-04-14
**Vai trò:** Supervisor Owner (Sprint 1)

---

## 1. Phần tôi phụ trách

Tôi phụ trách **Sprint 1 — Supervisor Orchestrator** (`graph.py`):

**Module/file tôi chịu trách nhiệm:**
- File chính: `graph.py`
- Functions tôi implement:
  - `AgentState` (TypedDict) — định nghĩa shared state toàn pipeline
  - `make_initial_state()` — khởi tạo state mặc định + `run_id` theo timestamp
  - `supervisor_node()` — phân tích task bằng keyword matching, quyết định route
  - `route_decision()` — đọc `supervisor_route` và dispatch đúng worker
  - `human_review_node()` — HITL placeholder, auto-approve trong lab mode
  - `build_graph()` — orchestrator Python-native (không dùng LangGraph)
  - `run_graph()` / `save_trace()` — public API cho `eval_trace.py`

**Cách công việc của tôi kết nối với phần của thành viên khác:**

`supervisor_node()` quyết định `supervisor_route`, các worker của Chu Thành Thông (`retrieval_worker`, `policy_tool_worker`, `synthesis_worker`) đọc giá trị đó để thực thi. MCP tools của Phùng Hữu Phú chỉ được gọi khi supervisor set `needs_tool=True`. `AgentState` là contract chung — nếu tôi thêm hoặc đổi key, tất cả sprint sau phải update theo.

**Bằng chứng:**

File `graph.py` — toàn bộ phần routing logic (lines 88–177) và `build_graph()` (lines 233–275) là code tôi viết trong Sprint 1. Trace thực tế xác nhận route_reason sinh ra từ code này:

```
"route_reason": "task chứa SLA/incident keyword: ['p1', 'sla', 'ticket']"
```

---

## 2. Tôi đã ra một quyết định kỹ thuật gì?

**Quyết định: Keyword-based routing thay vì gọi LLM để classify route**

Khi thiết kế `supervisor_node()`, tôi có hai lựa chọn:

**Option A (LLM classifier):**
```python
# Gọi Claude/GPT để classify: "retrieval" | "policy" | "human_review"
response = llm.invoke(f"Classify this task: {task}")
route = response.content.strip()
```

**Option B (Keyword matching — tôi chọn):**
```python
has_policy_kw = any(kw in task for kw in _POLICY_KW)
has_sla_kw    = any(kw in task for kw in _SLA_KW)
if has_policy_kw and has_sla_kw:
    route = "policy_tool_worker"  # multi-hop
elif has_policy_kw:
    route = "policy_tool_worker"
elif has_sla_kw:
    route = "retrieval_worker"
...
```

**Lý do chọn Option B:**
1. **Tốc độ:** Keyword matching chạy ~0 ms, LLM call mất 500–2000 ms. Với 15 test questions, tiết kiệm tổng 7.5–30 giây.
2. **Deterministic:** Cùng input luôn cho cùng route — dễ debug, dễ viết test case.
3. **Trace có thể explain:** `route_reason` ghi rõ keyword nào matched, không phải "LLM said so".
4. **Đủ chính xác:** Với bài toán CS/IT helpdesk có domain vocabulary hẹp (P1, SLA, hoàn tiền, Level 3...), keyword đủ để phân loại 15/15 route hợp lý.

**Trade-off đã chấp nhận:**

Keyword matching không hiểu ngữ nghĩa — câu hỏi viết tắt hoặc dùng synonym không có trong `_POLICY_KW`/`_SLA_KW` sẽ fallback sai. Nhưng với scope lab (domain đã biết, vocabulary cố định), trade-off này chấp nhận được.

**Bằng chứng từ trace:**

```json
"supervisor_route": "retrieval_worker",
"route_reason": "task chứa SLA/incident keyword: ['p1', 'sla', 'ticket']",
"latency_ms": 15892
```
*(15892ms là do warm-up embedding model lần đầu — supervisor bản thân chạy ~0ms, toàn bộ thời gian là ở retrieval_worker load ChromaDB)*

---

## 3. Tôi đã sửa một lỗi gì?

**Lỗi: Supervisor không detect multi-hop query → route sai, thiếu cross-doc retrieval**

**Symptom:**

Câu hỏi dạng *"P1 2am + cần Level 2 access — quy trình là gì?"* chứa cả SLA keyword (`p1`) lẫn policy/access keyword (`level 2`, `access`). Với logic routing ban đầu, `elif has_policy_kw` check trước → route thành `policy_tool_worker`. Nhưng policy_tool_worker không retrieve đủ thông tin từ `sla_p1_2026.txt`, thiếu nửa câu trả lời về quy trình P1.

**Root cause:**

```python
# Logic cũ — thứ tự check có vấn đề
if has_policy_kw:
    route = "policy_tool_worker"
elif has_sla_kw:
    route = "retrieval_worker"
# → Khi cả hai keywords xuất hiện, policy_kw thắng
#   nhưng không có signal nào để fetch cả hai docs
```

Cross-document query cần cả `access_control_sop.txt` VÀ `sla_p1_2026.txt`, nhưng không có path nào trong graph xử lý "cả hai".

**Cách sửa:**

```python
# Logic mới — check multi-hop TRƯỚC
if has_policy_kw and has_sla_kw:
    route = "policy_tool_worker"
    route_reason = "multi-hop: task chứa cả policy/access keyword VÀ SLA/P1 keyword → cần cross-doc retrieval"
    needs_tool = True
elif is_multihop:  # "đồng thời", "cả hai quy trình"
    route = "policy_tool_worker"
    needs_tool = True
elif has_policy_kw:
    ...
```

Đồng thời trong `build_graph()`, khi route là `policy_tool_worker`, graph chạy `retrieval_worker` TRƯỚC để đảm bảo policy_tool có context từ cả hai nguồn:

```python
elif route == "policy_tool_worker":
    state = retrieval_worker_node(state)   # fetch cả SLA + policy docs
    state = policy_tool_worker_node(state)  # MCP tool + policy check
    state = synthesis_worker_node(state)
```

**Bằng chứng trước/sau:**

| | Trước fix | Sau fix |
|-|-----------|---------|
| Task: "P1 2am + Level 2 access" | route=`policy_tool_worker`, thiếu SLA context | route=`policy_tool_worker`, retrieved cả `access_control_sop.txt` + `sla_p1_2026.txt` |
| route_reason | "task chứa policy keyword: ['level 2', 'access level']" | "multi-hop: task chứa cả policy/access keyword VÀ SLA/P1 keyword → cần cross-doc retrieval" |
| Sources trong answer | 1 doc | 2 docs |

---

## 4. Tôi tự đánh giá đóng góp của mình

**Tôi làm tốt nhất ở điểm nào?**

Thiết kế `AgentState` rõ ràng và đầy đủ từ đầu — `supervisor_route`, `route_reason`, `needs_tool`, `risk_high`, `hitl_triggered` đều là fields trong state, không phải biến local. Nhờ vậy `eval_trace.py` của Bùi Đức Tiến có thể đọc trace và tính metrics mà không cần thay đổi gì. `route_reason` trong mỗi trace giải thích được routing decision mà không cần đọc code.

**Tôi làm chưa tốt hoặc còn yếu ở điểm nào?**

Keyword list (`_POLICY_KW`, `_SLA_KW`) được hardcode thủ công, không có coverage test. Một số từ đồng nghĩa hoặc cách viết khác (e.g., "sự cố nghiêm trọng" thay vì "p1") sẽ fallback về `retrieval_worker` thay vì đúng route.

**Nhóm phụ thuộc vào tôi ở đâu?**

Toàn bộ pipeline phụ thuộc vào `supervisor_node()`. Nếu routing sai, worker đúng không được gọi → answer sai hoặc thiếu. Nếu `AgentState` thiếu field, `eval_trace.py` không tính được metrics (ví dụ: không có `supervisor_route` → không tính `routing_distribution`).

**Phần tôi phụ thuộc vào thành viên khác:**

Tôi cần workers của Chu Thành Thông export đúng function signature `run(state: AgentState) -> AgentState` — nếu signature thay đổi, `build_graph()` crash. Tôi cũng cần `mcp_server.py` của Phùng Hữu Phú chạy trước khi test policy_tool_worker với `needs_tool=True`.

---

## 5. Nếu có thêm 2 giờ, tôi sẽ làm gì?

**Cải tiến: Thêm confidence-based re-routing trong supervisor**

Từ trace của q07 (mức phạt tài chính vi phạm SLA): pipeline route đúng vào `retrieval_worker`, nhưng confidence chỉ đạt 0.0 vì thông tin không có trong docs → abstain đúng. Tuy nhiên supervisor không biết điều này trước khi chạy.

Nếu có 2 giờ thêm, tôi sẽ thêm một **second-pass routing**: sau khi `retrieval_worker` chạy, nếu `confidence < 0.3` và không có `retrieved_sources` liên quan, supervisor gửi task sang `policy_tool_worker` với MCP `search_kb` để thử thêm một lần nữa trước khi abstain. Cụ thể từ trace q07: `retrieved_sources = []`, `confidence = 0.0` — đây là signal rõ để retry với broader search thay vì trả lời ngay.

---
