# Routing Decisions Log — Lab Day 09

**Nhóm:** Vinno
**Ngày:** 2026-04-14

Ghi lại 5 quyết định routing thực tế từ trace (artifacts/traces/).

---

## Decision 1 — SLA retrieval query (q01)

**Task đầu vào:**
> "SLA xử lý ticket P1 là bao lâu?"

**Worker được chọn:** `retrieval_worker`

**route_reason (từ trace):**
> `task chứa SLA/incident keyword: ['p1', 'sla', 'ticket']`

**Kết quả:**
- Workers called: `retrieval_worker` → `synthesis_worker`
- Sources: `sla_p1_2026.txt`, `it_helpdesk_faq.txt`
- Confidence: 0.60
- Answer trích dẫn đúng SLA P1: phản hồi ban đầu 15 phút, resolution 4 giờ

**Phân tích:**
Supervisor phát hiện keyword "p1", "sla", "ticket" → route thẳng về retrieval_worker vì đây là câu hỏi tra cứu đơn giản, không cần policy check. Không cần MCP. Route này là tối ưu vì policy_tool_worker sẽ tốn thêm 1 MCP call không cần thiết.

---

## Decision 2 — Policy exception query (q07)

**Task đầu vào:**
> "Sản phẩm kỹ thuật số (license key) có được hoàn tiền không?"

**Worker được chọn:** `policy_tool_worker`

**route_reason (từ trace):**
> `task chứa policy/access keyword: ['hoàn tiền', 'license key', 'license']`

**Kết quả:**
- Workers called: `retrieval_worker` → `policy_tool_worker` → `synthesis_worker`
- Exception detected: `digital_product_exception` — sản phẩm kỹ thuật số không được hoàn tiền (Điều 3)
- Sources: `it_helpdesk_faq.txt`, `policy_refund_v4.txt`
- Confidence: 0.59 (penalty vì có exception)
- MCP calls: 0 (không cần ticket/access info)

**Phân tích:**
Supervisor phát hiện "license key" (digital product keyword) và "hoàn tiền" → route sang policy_tool_worker. Worker phát hiện đúng exception digital_product và set policy_applies=False. Đây là luồng hợp lý: retrieval lấy context, policy_tool phân tích exception, synthesis tổng hợp với cảnh báo rõ ràng.

---

## Decision 3 — HITL trigger (q09)

**Task đầu vào:**
> "ERR-403-AUTH là lỗi gì và cách xử lý?"

**Worker được chọn:** `human_review` → `retrieval_worker`

**route_reason (từ trace):**
> `unknown error code (ERR-xxx) + risk_high → escalate to human review | risk_high=True`

**Kết quả:**
- hitl_triggered: `True`
- Workers called: `human_review` → `retrieval_worker` → `synthesis_worker`
- Sources: `sla_p1_2026.txt`, `policy_refund_v4.txt` (không tìm thấy thông tin về ERR-403-AUTH)
- Confidence: 0.43 (thấp — không có evidence cụ thể)
- Answer: abstain — "Không đủ thông tin trong tài liệu nội bộ"

**Phân tích:**
Supervisor phát hiện mã lỗi không rõ (ERR-xxx pattern) và flag risk_high → escalate sang human_review trước khi tiếp tục. Sau khi auto-approve (lab mode), chạy retrieval nhưng không tìm thấy thông tin vì ERR-403-AUTH không có trong 5 docs. Synthesis dùng abstain đúng chuẩn — KHÔNG hallucinate. Đây là trường hợp pipeline xử lý tốt nhất có thể khi không có evidence.

---

## Decision 4 — Multi-hop cross-doc (q13)

**Task đầu vào:**
> "Contractor cần Admin Access (Level 3) để khắc phục sự cố P1 đang active. Quy trình cấp quyền tạm thời như thế nào?"

**Worker được chọn:** `policy_tool_worker` (multi-hop)

**route_reason (từ trace):**
> `multi-hop: task chứa cả policy/access keyword VÀ SLA/P1 keyword → cần cross-doc retrieval`

**Kết quả:**
- Workers called: `retrieval_worker` → `policy_tool_worker` → `synthesis_worker`
- MCP calls: `check_access_permission` (level=3, role=contractor, emergency=True), `get_ticket_info`
- Sources: `access_control_sop.txt`
- Confidence: 0.64
- MCP check_access_permission result: can_grant=True, required_approvers=[Line Manager, IT Admin, IT Security], emergency_override=False

**Phân tích:**
Supervisor phát hiện cả "access" (policy keyword) và "p1" (SLA keyword) trong cùng một task → route sang policy_tool_worker với multi-hop flag. Policy worker gọi MCP check_access_permission để kiểm tra Level 3 emergency: kết quả cho thấy Level 3 KHÔNG có emergency bypass (cần đủ 3 approvers). Đây là cross-doc reasoning đúng — kết hợp access_control_sop + sla_p1_2026.

---

## Decision 5 — Multi-hop 2 quy trình song song (q15)

**Task đầu vào:**
> "Ticket P1 lúc 2am. Cần cấp Level 2 access tạm thời cho contractor để thực hiện emergency fix. Đồng thời cần notify stakeholders theo SLA. Nêu đủ cả hai quy trình."

**Worker được chọn:** `policy_tool_worker` (multi-hop, risk_high=True)

**route_reason (từ trace):**
> `multi-hop: task chứa cả policy/access keyword VÀ SLA/P1 keyword → cần cross-doc retrieval | risk_high=True (emergency/khẩn cấp/lúc 2am)`

**Kết quả:**
- Workers called: `retrieval_worker` → `policy_tool_worker` → `synthesis_worker`
- MCP calls: `check_access_permission` (level=2, role=contractor, emergency=True), `get_ticket_info`
- Sources: `access_control_sop.txt`, `sla_p1_2026.txt`
- Confidence: 0.66
- MCP result: Level 2 CÓ emergency bypass với Line Manager + IT Admin on-call

**Phân tích:**
Đây là câu khó nhất (hardest, 16 điểm trong grading). Supervisor chính xác phát hiện "2am" (risk_high), "level 2" (policy), "p1" (SLA) → multi-hop route. Policy worker gọi MCP check_access_permission cho Level 2 emergency — kết quả cho thấy Level 2 CÓ emergency override (khác với Level 3). Sources từ 2 tài liệu khác nhau (access_control_sop + sla_p1_2026) chứng tỏ cross-doc retrieval thành công.

---

## Tổng kết routing distribution (15 test questions)

| Route            | Số câu | % |
|------------------|--------|---|
| retrieval_worker | 8      | 53% |
| policy_tool_worker | 7    | 46% |
| human_review (HITL) | 1   | 6% (q09) |

- MCP tools được gọi trong 3 queries (q03, q13, q15)
- HITL trigger 1 lần (q09 — unknown error code)
- Tất cả 15 câu thành công, 0 crash
