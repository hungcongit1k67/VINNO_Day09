# Báo Cáo Cá Nhân — Lab Day 09: Multi-Agent Orchestration

**Họ và tên:** Phùng Hữu Phú  
**Vai trò trong nhóm:** MCP Owner (Sprint 3)  
**Ngày nộp:** 2026-04-14  
**Độ dài:** ~650 từ

---

## 1. Tôi phụ trách phần nào? (100–150 từ)

Trong Day 09, tôi phụ trách chính Sprint 3 với vai trò MCP Owner. Tôi làm trực tiếp trên `mcp_server.py` và phần tích hợp trong `workers/policy_tool.py`. Ở `mcp_server.py`, tôi xây lớp MCP mock theo hướng server-side tool registry gồm `TOOL_SCHEMAS`, `TOOL_REGISTRY`, `list_tools()` và `dispatch_tool()`, đồng thời triển khai các tool `search_kb`, `get_ticket_info`, `check_access_permission`, `create_ticket` (đáp ứng yêu cầu >= 2 tools).

Ở phía worker, tôi dùng `_call_mcp_tool()` để policy worker gọi tool theo format chung (`tool`, `input`, `output`, `error`, `timestamp`) thay vì hard-code API riêng cho từng case. Việc này kết nối trực tiếp với supervisor: khi route vào `policy_tool_worker` và `needs_tool=True`, worker sẽ gọi MCP rồi trả kết quả để synthesis dùng tiếp.

**Module/file tôi chịu trách nhiệm:**
- File chính: `mcp_server.py`, `workers/policy_tool.py`
- Functions tôi implement/chịu trách nhiệm: `list_tools()`, `dispatch_tool()`, `tool_search_kb()`, `tool_get_ticket_info()`, `_call_mcp_tool()`

**Cách công việc của tôi kết nối với phần của thành viên khác:**
- Supervisor quyết định route + `needs_tool`
- Policy worker gọi MCP tool để lấy dữ liệu thật theo task
- Synthesis dùng output MCP/policy để tổng hợp câu trả lời cuối

**Bằng chứng:**
- Trace `artifacts/traces/run_20260414_123032_748703.json` có `mcp_tools_used` chứa cả `search_kb` và `get_ticket_info`.

---

## 2. Tôi đã ra một quyết định kỹ thuật gì? (150–200 từ)

**Quyết định:** Tôi chọn thiết kế MCP theo dạng **discovery + dispatch generic** (`list_tools`/`dispatch_tool`) thay vì để policy worker import và gọi trực tiếp từng hàm tool.

Nếu dùng cách gọi trực tiếp theo if/else trong worker thì ngắn hơn lúc đầu, nhưng coupling cao: thêm tool mới sẽ phải sửa worker logic. Tôi chọn tách thành registry phía MCP server để worker chỉ cần truyền `tool_name` + `tool_input`; phần thực thi ở server quyết định. Cách này giúp mở rộng tool nhanh hơn, chuẩn hóa trace, và bám đúng tinh thần Sprint 3 là worker gọi external capability qua interface thống nhất.

**Trade-off đã chấp nhận:**
- Dispatch động có thể lỗi runtime (sai tên tool/sai tham số), nên tôi thêm guard:
  - báo lỗi tool không tồn tại,
  - bắt `TypeError` và trả luôn schema input để debug nhanh.

**Bằng chứng từ code/trace:**
- `mcp_server.py` có `TOOL_REGISTRY`, `list_tools()`, `dispatch_tool()`.
- `workers/policy_tool.py` gọi `_call_mcp_tool("search_kb", ...)` và `_call_mcp_tool("get_ticket_info", ...)`.
- Trace ghi rõ từng lần gọi trong `mcp_tools_used`, đủ `input/output/timestamp`.

---

## 3. Tôi đã sửa một lỗi gì? (150–200 từ)

**Lỗi:** Tra cứu ticket có thể fail khi định dạng `ticket_id` không đồng nhất chữ hoa/chữ thường.

**Symptom (pipeline làm gì sai?):**  
Trong luồng policy, có những input ticket id không đúng format key trong mock DB. Khi đó tool trả về “không tìm thấy ticket”, khiến pipeline thiếu dữ liệu `sla_deadline`, `notifications_sent`, và phần trả lời các câu về P1/escalation bị yếu hoặc thiếu.

**Root cause:**  
Lookup dictionary trong `tool_get_ticket_info()` phụ thuộc key đúng format, trong khi dữ liệu mock dùng key in hoa (`P1-LATEST`, `IT-1234`), còn input có thể biến thể.

**Cách sửa:**  
Tôi normalize input trước khi lookup bằng `ticket_id.upper()`. Sau sửa, cùng một ticket id vẫn tra ra kết quả ngay cả khi input không đồng nhất format.

**Bằng chứng trước/sau:**
- Trước: có khả năng rơi vào nhánh error “Ticket ... không tìm thấy”.
- Sau: `tool_get_ticket_info()` luôn chuẩn hóa ID trước lookup.
- Trace `run_20260414_123032_748703.json` cho thấy tool trả đủ fields:
  `priority`, `status`, `sla_deadline`, `notifications_sent`, chứng minh luồng MCP call hoạt động ổn định hơn.

---

## 4. Tôi tự đánh giá đóng góp của mình (100–150 từ)

**Tôi làm tốt nhất ở điểm nào?**  
Tôi làm tốt ở việc tạo boundary rõ ràng giữa worker và tool layer: worker gọi qua interface thống nhất thay vì gọi trực tiếp từng hàm. Điều này tăng tính modular và giúp trace dễ đọc, dễ debug hơn.

**Tôi làm chưa tốt hoặc còn yếu ở điểm nào?**  
Tôi mới dừng ở MCP mock in-process. Tôi chưa đẩy lên HTTP MCP server thật nên chưa tận dụng được phần advanced bonus.

**Nhóm phụ thuộc vào tôi ở đâu?**  
Nhóm phụ thuộc vào lớp MCP integration: nếu phần này lỗi, policy worker thiếu dữ liệu và synthesis khó đưa ra câu trả lời có căn cứ.

**Phần tôi phụ thuộc vào thành viên khác:**  
Tôi phụ thuộc supervisor owner để route/`needs_tool` đúng, và phụ thuộc synthesis owner để tận dụng tối đa output từ MCP trong final answer.

---

## 5. Nếu có thêm 2 giờ, tôi sẽ làm gì? (50–100 từ)

Tôi sẽ nâng MCP từ mock in-process lên HTTP server thật (advanced option), thêm endpoint kiểu `tools/list` và `tools/call`, sau đó sửa `_call_mcp_tool()` để gọi qua HTTP. Lý do: trace hiện đã có format `mcp_tools_used` ổn định, nên đổi transport sẽ ít ảnh hưởng contract hiện tại nhưng tăng tính thực tế kiến trúc và có cơ hội lấy bonus +2 theo rubric Sprint 3.

