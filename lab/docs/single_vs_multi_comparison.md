# Single Agent vs Multi-Agent Comparison — Lab Day 09

**Nhóm:** Vinno
**Ngày:** 2026-04-14

So sánh Day 08 (RAG pipeline đơn) vs Day 09 (Supervisor-Worker multi-agent).

---

## Metric 1: Debuggability (Khả năng debug khi sai)

### Day 08 — Single Agent RAG
- Khi pipeline trả lời sai, không rõ lỗi ở bước nào: retrieve sai? generate sai? context thiếu?
- Không có worker_io_log, không có route_reason
- Phải debug toàn bộ pipeline mỗi lần

### Day 09 — Multi-Agent
- Mỗi bước có log riêng: `worker_io_logs`, `history`, `route_reason`
- Ví dụ từ trace q09 (ERR-403-AUTH):
  ```json
  "history": [
    "[supervisor] route=human_review | reason=unknown error code (ERR-xxx) + risk_high",
    "[retrieval_worker] retrieved 3 chunks from ['sla_p1_2026.txt', ...]",
    "[synthesis_worker] answer generated, confidence=0.43, sources=[...]"
  ]
  ```
- Nhìn vào trace biết ngay: supervisor route đúng, retrieval không tìm thấy ERR-403-AUTH, confidence thấp (0.43) → abstain đúng
- Có thể test từng worker độc lập: `python workers/retrieval.py` chạy được không qua graph

**Kết luận Metric 1:** Multi-agent tốt hơn single agent về debuggability. Khi sai, biết chính xác bước nào và tại sao.

---

## Metric 2: Routing Visibility (Khả năng giải thích quyết định)

### Day 08 — Single Agent RAG
- Một pipeline: retrieve → generate. Không có khái niệm "route"
- Không rõ tại sao một câu được xử lý theo một cách nào đó
- Policy exception và SLA query được xử lý giống nhau (cùng prompt)

### Day 09 — Multi-Agent
- Mỗi query có `supervisor_route` và `route_reason` rõ ràng trong trace:

| Task | Route | route_reason |
|------|-------|-------------|
| "SLA P1 bao lâu?" | retrieval_worker | task chứa SLA/incident keyword: ['p1','sla','ticket'] |
| "Flash Sale hoàn tiền?" | policy_tool_worker | task chứa policy keyword: ['hoàn tiền','flash sale'] |
| "ERR-403-AUTH?" | human_review | unknown error code + risk_high |
| "Level 3 + P1 khẩn cấp" | policy_tool_worker | multi-hop: cả policy VÀ SLA keyword |

- Supervisor cung cấp audit trail: có thể chứng minh tại sao router chọn worker nào
- Bonus: multi-hop query (cả policy và SLA) được phát hiện và xử lý thành cross-doc retrieval từ 2 tài liệu

**Kết luận Metric 2:** Multi-agent có routing visibility hoàn toàn. Single agent "black box" về quyết định xử lý.

---

## Metric 3: Latency (Thời gian xử lý)

### Day 08 — Baseline (ước tính)
- Single LLM call cho cả retrieve + generate: ~2-5 giây (phụ thuộc LLM)
- Không có warm-up cost đáng kể

### Day 09 — Multi-Agent (từ trace thực tế)
- Query đầu tiên (load embedding model): ~15,892 ms (warm-up)
- Các query tiếp theo: 11–34 ms (sau khi model đã cache)
- Average latency (bao gồm warm-up): 1,077 ms (tính toán từ 15 queries)
- Average latency (bỏ query đầu): ~20 ms

**So sánh:**
| | Day 08 (ước tính) | Day 09 (thực tế) |
|--|--|--|
| First query | ~2,000 ms | ~15,892 ms (warm-up) |
| Subsequent | ~2,000 ms | ~20 ms (cached) |
| LLM required | Yes (always) | No (extractive fallback) |

**Kết luận Metric 3:** Multi-agent có latency cao hơn ở query đầu (warm-up embedding model) nhưng rẻ hơn đáng kể sau đó vì sử dụng extractive synthesis (không cần LLM call mỗi lần). Trong production, embedding model sẽ được pre-loaded → không còn overhead.

---

## Metric 4: MCP Extensibility (Khả năng mở rộng)

### Day 08 — Single Agent RAG
- Thêm capability = sửa code pipeline trực tiếp
- Ví dụ: muốn gọi ticket API phải sửa retrieve_and_generate() function
- Change radius lớn, dễ làm hỏng các chức năng cũ

### Day 09 — Multi-Agent + MCP
- Thêm capability = thêm tool mới vào mcp_server.py (TOOL_REGISTRY)
- Workers gọi qua dispatch_tool() — không cần biết implementation
- Ví dụ: thêm `check_access_permission` trong Sprint 3 mà không cần sửa graph.py hay synthesis.py
- MCP calls được audit trong trace: `mcp_tools_used` field

Từ trace q13 và q15:
```json
"mcp_tools_used": [
  {"tool": "check_access_permission", "input": {"access_level": 3, "requester_role": "contractor", "is_emergency": true}, "timestamp": "..."},
  {"tool": "get_ticket_info", "input": {"ticket_id": "P1-LATEST"}, "timestamp": "..."}
]
```

**Kết luận Metric 4:** Multi-agent có khả năng mở rộng vượt trội. MCP isolation giúp thêm/xóa tool mà không làm hỏng pipeline.

---

## Tổng kết so sánh

| Metric                  | Day 08 Single Agent | Day 09 Multi-Agent | Winner  |
|-------------------------|---------------------|--------------------|---------|
| Debuggability           | Thấp (black box)    | Cao (trace rõ ràng) | Day 09 |
| Routing visibility      | Không có            | Có route_reason     | Day 09 |
| Latency (warm queries)  | ~2,000 ms           | ~20 ms              | Day 09 |
| Latency (cold start)    | ~2,000 ms           | ~15,892 ms          | Day 08 |
| MCP extensibility       | Không có            | Có (4 tools)        | Day 09 |
| Policy exception detect | Implicit            | Explicit (rule-based)| Day 09 |
| HITL support            | Không có            | Có (human_review node)| Day 09 |

**Kết luận chung:**
Multi-agent (Day 09) tốt hơn single agent (Day 08) ở 6/7 metrics. Điểm yếu duy nhất là cold-start latency (phải load embedding model lần đầu). Trong production environment, đây không phải vấn đề vì model sẽ được pre-loaded. Quan trọng hơn là khả năng debug, explain, và mở rộng — đây chính là giá trị cốt lõi của Supervisor-Worker pattern.
