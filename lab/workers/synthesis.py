import os
import json

WORKER_NAME = "synthesis_worker"

SYSTEM_PROMPT = """Bạn là trợ lý IT Helpdesk nội bộ chuyên nghiệp.

QUY TẮC CỐT LÕI:
1. NGUỒN TIN: Chỉ sử dụng thông tin từ "TÀI LIỆU THAM KHẢO" và "POLICY EXCEPTIONS" được cung cấp. KHÔNG dùng kiến thức bên ngoài.
2. TRÍCH DẪN: Mỗi câu khẳng định quan trọng phải đi kèm nguồn trong ngoặc vuông ngay sau câu đó, ví dụ: [filename.txt].
3. NGOẠI LỆ: Nếu có "POLICY EXCEPTIONS", bạn PHẢI ưu tiên trình bày các ngoại lệ này rõ ràng vì chúng quyết định kết quả cuối cùng.
4. THÀNH THẬT: Nếu tài liệu không chứa câu trả lời, hãy phản hồi: "Tôi rất tiếc, tài liệu nội bộ hiện không có đủ thông tin để trả lời câu hỏi này."
5. PHONG CÁCH: Trình bày súc tích, sử dụng bullet points cho danh sách.
"""

def _call_llm(messages: list) -> str:
    """
    Hiện thực hóa gọi LLM. Ưu tiên OpenAI, fallback sang Gemini.
    """
    # 1. Thử OpenAI
    api_key_openai = os.getenv("OPENAI_API_KEY")
    if api_key_openai:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key_openai)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.0, # Giảm tối đa sự sáng tạo để tăng độ chính xác
                max_tokens=800,
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"⚠️ OpenAI Error: {e}")

    # 2. Thử Gemini (Fallback)
    api_key_gemini = os.getenv("GOOGLE_API_KEY")
    if api_key_gemini:
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key_gemini)
            model = genai.GenerativeModel("gemini-1.5-flash")
            # Convert OpenAI format to Gemini format
            prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            print(f"⚠️ Gemini Error: {e}")

    return "[SYNTHESIS ERROR] Không thể kết nối tới bất kỳ LLM provider nào. Vui lòng kiểm tra API Key."


def _estimate_confidence(chunks: list, answer: str, policy_result: dict) -> float:
    """
    Tính toán mức độ tin cậy dựa trên chất lượng retrieval và nội dung câu trả lời.
    """
    # Khởi điểm
    base_confidence = 0.0
    
    # 1. Check Retrieval Quality (Max 0.6)
    if chunks:
        # Lấy score cao nhất làm đại diện cho độ khớp tài liệu
        top_score = max(c.get("score", 0) for c in chunks)
        base_confidence += (top_score * 0.6)
    
    # 2. Check Answer Content (Penalty/Bonus)
    abstain_phrases = ["không đủ thông tin", "không tìm thấy", "không có thông tin", "không được cung cấp"]
    if any(phrase in answer.lower() for phrase in abstain_phrases):
        return round(min(base_confidence, 0.3), 2) # Trả lời kiểu "không biết" thì confidence thấp
    
    # 3. Check Policy Result (Max 0.4)
    if policy_result:
        # Nếu đã qua phân tích policy rõ ràng (dù là từ chối hay đồng ý)
        base_confidence += 0.3
        # Bonus nếu không có mâu thuẫn phức tạp
        if not policy_result.get("exceptions_found"):
            base_confidence += 0.1

    # 4. Final adjustments
    # Giới hạn trong khoảng [0.1, 0.98]
    final_score = min(0.98, max(0.1, base_confidence))
    return round(final_score, 2)


def _build_context(chunks: list, policy_result: dict) -> str:
    """Xây dựng context string giàu thông tin hơn."""
    context_blocks = []

    if chunks:
        context_blocks.append("=== TÀI LIỆU THAM KHẢO ===")
        for i, chunk in enumerate(chunks, 1):
            source = chunk.get("source", "N/A")
            content = chunk.get("text", "").strip()
            context_blocks.append(f"Tài liệu [{i}] (Nguồn: {source}):\n{content}")

    if policy_result:
        context_blocks.append("\n=== KẾT QUẢ PHÂN TÍCH CHÍNH SÁCH ===")
        applies = "Được áp dụng" if policy_result.get("policy_applies") else "Bị từ chối/Cần xem xét lại"
        context_blocks.append(f"Trạng thái: {applies}")
        
        exceptions = policy_result.get("exceptions_found", [])
        if exceptions:
            context_blocks.append("Các ngoại lệ phát hiện được:")
            for ex in exceptions:
                context_blocks.append(f"- {ex.get('rule')} (Loại: {ex.get('type')})")
        
        if policy_result.get("policy_version_note"):
            context_blocks.append(f"Lưu ý phiên bản: {policy_result['policy_version_note']}")

    return "\n\n".join(context_blocks) if context_blocks else "Không tìm thấy dữ liệu liên quan."


def synthesize(task: str, chunks: list, policy_result: dict) -> dict:
    """
    Thực hiện quy trình Synthesis.
    """
    context = _build_context(chunks, policy_result)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"CÂU HỎI CỦA NGƯỜI DÙNG: {task}\n\n{context}\n\nHãy tổng hợp câu trả lời:"
        }
    ]

    answer = _call_llm(messages)
    
    # Thu thập tất cả sources
    sources = list(set([c.get("source") for c in chunks if c.get("source")]))
    
    # Tính toán độ tin cậy
    confidence = _estimate_confidence(chunks, answer, policy_result)

    return {
        "answer": answer,
        "sources": sources,
        "confidence": confidence,
    }


def run(state: dict) -> dict:
    """
    Worker entry point — gọi từ graph.py.
    """
    task = state.get("task", "")
    chunks = state.get("retrieved_chunks", [])
    policy_result = state.get("policy_result", {})

    state.setdefault("workers_called", [])
    state.setdefault("history", [])
    state["workers_called"].append(WORKER_NAME)

    worker_io = {
        "worker": WORKER_NAME,
        "input": {
            "task": task,
            "chunks_count": len(chunks),
            "has_policy": bool(policy_result),
        },
        "output": None,
        "error": None,
    }

    try:
        result = synthesize(task, chunks, policy_result)
        state["final_answer"] = result["answer"]
        state["sources"] = result["sources"]
        state["confidence"] = result["confidence"]

        worker_io["output"] = {
            "answer_length": len(result["answer"]),
            "sources": result["sources"],
            "confidence": result["confidence"],
        }
        state["history"].append(
            f"[{WORKER_NAME}] answer generated, confidence={result['confidence']}, "
            f"sources={result['sources']}"
        )

    except Exception as e:
        worker_io["error"] = {"code": "SYNTHESIS_FAILED", "reason": str(e)}
        state["final_answer"] = f"SYNTHESIS_ERROR: {e}"
        state["confidence"] = 0.0
        state["history"].append(f"[{WORKER_NAME}] ERROR: {e}")

    state.setdefault("worker_io_logs", []).append(worker_io)
    return state


# ─────────────────────────────────────────────
# Test độc lập
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("Synthesis Worker — Standalone Test")
    print("=" * 50)

    test_state = {
        "task": "SLA ticket P1 là bao lâu?",
        "retrieved_chunks": [
            {
                "text": "Ticket P1: Phản hồi ban đầu 15 phút kể từ khi ticket được tạo. Xử lý và khắc phục 4 giờ. Escalation: tự động escalate lên Senior Engineer nếu không có phản hồi trong 10 phút.",
                "source": "sla_p1_2026.txt",
                "score": 0.92,
            }
        ],
        "policy_result": {},
    }

    result = run(test_state.copy())
    print(f"\nAnswer:\n{result['final_answer']}")
    print(f"\nSources: {result['sources']}")
    print(f"Confidence: {result['confidence']}")

    print("\n--- Test 2: Exception case ---")
    test_state2 = {
        "task": "Khách hàng Flash Sale yêu cầu hoàn tiền vì lỗi nhà sản xuất.",
        "retrieved_chunks": [
            {
                "text": "Ngoại lệ: Đơn hàng Flash Sale không được hoàn tiền theo Điều 3 chính sách v4.",
                "source": "policy_refund_v4.txt",
                "score": 0.88,
            }
        ],
        "policy_result": {
            "policy_applies": False,
            "exceptions_found": [{"type": "flash_sale_exception", "rule": "Flash Sale không được hoàn tiền."}],
        },
    }
    result2 = run(test_state2.copy())
    print(f"\nAnswer:\n{result2['final_answer']}")
    print(f"Confidence: {result2['confidence']}")

    print("\n✅ synthesis_worker test done.")
