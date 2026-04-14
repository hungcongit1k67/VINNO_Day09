# System Architecture — Multi-Agent CS + IT Helpdesk

**Nhóm:** Vinno
**Ngày:** 2026-04-14  
**Version:** 1.0

---

## Tổng quan kiến trúc

Hệ thống trợ lý nội bộ CS + IT Helpdesk Day 09 được refactor từ RAG pipeline đơn nhất (Day 08) thành **Supervisor-Worker multi-agent graph** với vai trò phân tách rõ ràng.

---

## Pipeline Flow (ASCII Diagram)

```
User Query
    |
    v
+----------------------------------+
|         SUPERVISOR NODE          |
|  - Phân tích task keywords       |
|  - Quyết định route              |
|  - Set: needs_tool, risk_high    |
|  - Ghi route_reason vào state    |
+---------------+------------------+
                |
        route_decision()
                |
     +----------+-----------+
     |          |           |
     v          v           v
[retrieval]  [policy_tool] [human_review]
 _worker      _worker       (HITL)
     |          |             |
     |          +- MCP:       |
     |          |  search_kb  +---> retrieval_worker
     |          |  check_access        |
     |          |  get_ticket_info     |
     |          |                      |
     +--------+-+              --------+
              |
              v
    +------------------+
    |  SYNTHESIS       |
    |  WORKER          |
    |  - Build answer  |
    |  - Add citation  |
    |  - Calc conf.    |
    +--------+---------+
             |
             v
    AgentState (final_answer, sources,
                confidence, trace, ...)
```

---

## Vai trò từng thành phần

### Supervisor (graph.py: supervisor_node)
- **Nhận:** câu hỏi từ user
- **Làm:** phân tích keyword => quyết định route, set needs_tool, risk_high, ghi route_reason
- **Không làm:** KHÔNG tự trả lời domain knowledge, không gọi ChromaDB trực tiếp
- **Ranh giới:** supervisor chỉ ra lệnh, không thực thi

### Retrieval Worker (workers/retrieval.py)
- **Nhận:** task + top_k từ state
- **Làm:** embed query => query ChromaDB => trả về top-k chunks có score
- **Không làm:** không đánh giá policy, không tổng hợp answer
- **Stateless:** test độc lập được, không phụ thuộc worker khác

### Policy Tool Worker (workers/policy_tool.py)
- **Nhận:** task + retrieved_chunks + needs_tool từ state
- **Làm:** phát hiện exceptions (Flash Sale, digital product, activated), kiểm tra access level, gọi MCP tools
- **MCP tools gọi:** search_kb, check_access_permission, get_ticket_info
- **Không làm:** không tổng hợp answer cuối, không direct query ChromaDB

### Synthesis Worker (workers/synthesis.py)
- **Nhận:** task + retrieved_chunks + policy_result từ state
- **Làm:** build grounded answer với citation [source], tính confidence
- **Fallback:** extractive synthesis khi không có LLM API key
- **Không làm:** không hallucinate, không dùng kiến thức ngoài context

### MCP Server (mcp_server.py)
- **Expose tools:** search_kb, get_ticket_info, check_access_permission, create_ticket
- **Interface:** dispatch_tool(tool_name, tool_input) -> dict kết quả
- **Design:** Mock Python class (Standard level)

---

## Routing Logic (Supervisor Decision Tree)

```
task có policy keyword VÀ SLA keyword?
    -> YES -> policy_tool_worker (multi-hop, needs_tool=True)
    -> NO:
        task có policy/access keyword?
            -> YES -> policy_tool_worker (needs_tool=True)
            -> NO:
                task có SLA/P1/ticket keyword?
                    -> YES -> retrieval_worker
                    -> NO:
                        task có ERR-xxx + risk_high?
                            -> YES -> human_review -> retrieval_worker
                            -> NO -> retrieval_worker (default)
```

**Policy keywords:** hoàn tiền, refund, flash sale, license, cấp quyền, access, level 2/3/4  
**SLA keywords:** P1, SLA, ticket, escalation, sự cố, incident, on-call

---

## Lý do chọn Supervisor-Worker thay vì Single Agent

| Vấn đề Single Agent (Day 08)                          | Giải pháp Multi-Agent (Day 09)                     |
|-------------------------------------------------------|----------------------------------------------------|
| Một agent vừa retrieve, vừa kiểm tra policy, vừa tổng hợp | Mỗi worker có domain skill riêng biệt          |
| Lỗi không rõ ở bước nào                               | Trace ghi rõ từng bước: route_reason, worker_io_logs |
| Không thể test từng phần                              | Mỗi worker test độc lập được                       |
| Không thể thêm capability không ảnh hưởng code cũ     | MCP server mở rộng capability không cần sửa workers |
| HITL không có điểm dừng tự nhiên                      | human_review node = điểm dừng rõ ràng trong graph  |

---

## State Management

AgentState (TypedDict) là shared state đi xuyên toàn graph:

- task: str — Input không đổi
- supervisor_route: str — Routing decision
- route_reason: str — Lý do route (traceable)
- risk_high: bool — Flag cho HITL
- needs_tool: bool — Flag cho MCP
- retrieved_chunks: list — Evidence từ ChromaDB
- policy_result: dict — Policy analysis + access check
- mcp_tools_used: list — Audit trail MCP calls
- final_answer: str — Output
- confidence: float — 0.0-1.0
- workers_called: list — Execution trace
- history: list — Step-by-step log

---

## Kết quả đo được từ 15 test questions

| Metric                          | Giá trị           |
|---------------------------------|-------------------|
| Tổng câu hỏi                    | 15                |
| Thành công                      | 15/15 (100%)      |
| Route: retrieval_worker         | 8/15 (53%)        |
| Route: policy_tool_worker       | 7/15 (46%)        |
| HITL triggered                  | 1/15 (q09)        |
| MCP tool calls                  | 3 queries         |
| Avg confidence                  | 0.634             |
| Avg latency (sau warm-up)       | ~22ms             |
| Docs covered                    | 5/5 documents     |
