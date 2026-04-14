"""
workers/synthesis.py — Synthesis Worker
Sprint 2: Tổng hợp câu trả lời từ retrieved_chunks và policy_result.

Chiến lược:
  1. Thử gọi LLM (Anthropic → OpenAI → Gemini) nếu API key có sẵn.
  2. Fallback: extractive synthesis grounded 100% vào context (không hallucinate).

Output:
  - final_answer: câu trả lời với citation [source]
  - sources: list nguồn tài liệu
  - confidence: 0.0–1.0 dựa vào chunk scores
"""

import os

WORKER_NAME = "synthesis_worker"

SYSTEM_PROMPT = """Bạn là trợ lý IT Helpdesk nội bộ.

Quy tắc nghiêm ngặt:
1. CHỈ trả lời dựa vào context được cung cấp. KHÔNG dùng kiến thức ngoài.
2. Nếu context không đủ để trả lời → nói rõ "Không đủ thông tin trong tài liệu nội bộ".
3. Trích dẫn nguồn cuối mỗi câu quan trọng: [tên_file].
4. Trả lời súc tích, có cấu trúc. Không dài dòng.
5. Nếu có exceptions/ngoại lệ → nêu rõ ràng TRƯỚC khi kết luận.
6. Nếu cần thông tin từ nhiều tài liệu → tổng hợp rõ từng phần.
"""


# ─────────────────────────────────────────────
# LLM Callers
# ─────────────────────────────────────────────

def _call_anthropic(messages: list) -> str:
    """Gọi Anthropic Claude (claude-haiku-4-5)."""
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)
    # Convert messages format
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user_msgs = [m for m in messages if m["role"] != "system"]
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=system,
        messages=user_msgs,
    )
    return response.content[0].text


def _call_openai(messages: list) -> str:
    """Gọi OpenAI GPT-4o-mini."""
    from openai import OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.1,
        max_tokens=600,
    )
    return response.choices[0].message.content


def _call_gemini(messages: list) -> str:
    """Gọi Google Gemini."""
    import google.generativeai as genai
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not set")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    combined = "\n".join([m["content"] for m in messages])
    return model.generate_content(combined).text


def _call_llm(messages: list) -> str:
    """Thử lần lượt Anthropic → OpenAI → Gemini → extractive fallback."""
    for caller in [_call_anthropic, _call_openai, _call_gemini]:
        try:
            return caller(messages)
        except Exception:
            continue
    return ""  # Signal to use extractive


# ─────────────────────────────────────────────
# Context Builder
# ─────────────────────────────────────────────

def _build_context(chunks: list, policy_result: dict) -> str:
    parts = []
    if chunks:
        parts.append("=== TAI LIEU THAM KHAO ===")
        for i, chunk in enumerate(chunks, 1):
            source = chunk.get("source", "unknown")
            text = chunk.get("text", "")
            score = chunk.get("score", 0)
            parts.append(f"[{i}] Nguon: {source} (relevance: {score:.2f})\n{text}")

    if policy_result and policy_result.get("exceptions_found"):
        parts.append("\n=== POLICY EXCEPTIONS ===")
        for ex in policy_result["exceptions_found"]:
            parts.append(f"- {ex.get('rule', '')}")

    if policy_result and policy_result.get("policy_version_note"):
        parts.append(f"\n=== GHI CHU PHIEN BAN ===\n{policy_result['policy_version_note']}")

    return "\n\n".join(parts) if parts else "(Khong co context)"


# ─────────────────────────────────────────────
# Extractive Synthesis (no LLM needed)
# ─────────────────────────────────────────────

_HEADER_SIGNALS = [
    "source:", "department:", "effective date:", "access:", "ngay hieu luc",
    "nguon:", "lich su phien ban", "cong cu lien quan",
]


def _is_header_chunk(text: str) -> bool:
    """True nếu chunk chỉ là metadata header của tài liệu, không chứa nội dung chính."""
    low = text.lower()
    signal_count = sum(1 for s in _HEADER_SIGNALS if s in low)
    # Header chunk thường có >= 2 metadata signals và ngắn
    return signal_count >= 2 and len(text) < 500


def _clean_chunk_text(text: str) -> str:
    """Xóa dòng metadata (Source:, Department:, v.v.) khỏi chunk text."""
    lines = text.splitlines()
    clean = []
    for line in lines:
        low = line.lower().strip()
        # Skip pure metadata lines
        if any(low.startswith(s) for s in _HEADER_SIGNALS):
            continue
        if low.startswith("===") and len(line.strip()) < 6:
            continue
        clean.append(line)
    return "\n".join(clean).strip()


def _synthesize_extractive(task: str, chunks: list, policy_result: dict) -> str:
    """
    Tổng hợp grounded từ chunks — không LLM, không hallucinate.
    Trả về answer có citation [source].
    """
    # Case: no evidence → abstain
    if not chunks:
        return (
            "Khong du thong tin trong tai lieu noi bo de tra loi cau hoi nay.\n"
            "Vui long lien he IT Helpdesk (ext. 9999) hoac CS Team de duoc ho tro truc tiep."
        )

    parts = []

    # 1. Exception / policy check
    exceptions = (policy_result or {}).get("exceptions_found", [])
    if exceptions:
        parts.append("**Luu y — Ngoai le ap dung:**")
        for exc in exceptions:
            rule = exc.get("rule", "")
            src = exc.get("source", "")
            parts.append(f"- {rule} [{src}]")

        policy_applies = (policy_result or {}).get("policy_applies", True)
        if not policy_applies:
            parts.append(
                "\n**Ket luan:** Yeu cau KHONG duoc xu ly do co ngoai le ap dung.\n"
                "Lien he CS Team de biet them chi tiet."
            )

    # 2. Access check result from MCP
    acc = (policy_result or {}).get("access_check")
    if acc:
        can = acc.get("can_grant")
        approvers = acc.get("required_approvers", [])
        emergency = acc.get("emergency_override", False)
        notes = acc.get("notes", [])
        parts.append(
            f"\n**Ket qua kiem tra quyen truy cap (MCP check_access_permission):**\n"
            f"- Co the cap quyen: {'Co' if can else 'Khong'}\n"
            f"- Can phe duyet boi: {', '.join(approvers)}\n"
            f"- Emergency override: {'Co' if emergency else 'Khong'}"
        )
        for note in notes:
            parts.append(f"  Ghi chu: {note}")

    # 3. Policy version note (temporal scoping)
    version_note = (policy_result or {}).get("policy_version_note", "")
    if version_note:
        parts.append(f"\n**Ghi chu phien ban chinh sach:**\n{version_note}")

    # 4. Evidence from content chunks (skip header-only chunks)
    content_chunks = [c for c in chunks if not _is_header_chunk(c.get("text", ""))]
    if not content_chunks:
        content_chunks = chunks  # fallback: use all

    if parts:
        parts.append("\n**Thong tin tu tai lieu:**")

    added_texts = set()
    added_count = 0
    for chunk in content_chunks:
        text = _clean_chunk_text(chunk.get("text", ""))
        source = chunk.get("source", "unknown")
        score = chunk.get("score", 0)

        if not text or score < 0.10:
            continue
        text_key = text[:100]
        if text_key in added_texts:
            continue
        added_texts.add(text_key)

        added_count += 1
        parts.append(f"[{added_count}] {text}\n    Nguon: [{source}]")

    # Fallback: nếu không có gì được thêm, dùng chunk đầu tiên
    if added_count == 0:
        best = chunks[0]
        text = _clean_chunk_text(best.get("text", ""))
        parts.append(f"[1] {text}\n    Nguon: [{best.get('source', 'unknown')}]")

    return "\n\n".join(parts)


# ─────────────────────────────────────────────
# Confidence Estimator
# ─────────────────────────────────────────────

def _estimate_confidence(chunks: list, answer: str, policy_result: dict) -> float:
    if not chunks:
        return 0.1
    if "khong du thong tin" in answer.lower() or "abstain" in answer.lower():
        return 0.2
    avg_score = sum(c.get("score", 0) for c in chunks) / len(chunks)
    penalty = 0.05 * len((policy_result or {}).get("exceptions_found", []))
    return round(max(0.15, min(0.93, avg_score - penalty)), 2)


# ─────────────────────────────────────────────
# Main Synthesize
# ─────────────────────────────────────────────

def synthesize(task: str, chunks: list, policy_result: dict) -> dict:
    """
    Tổng hợp answer. Thử LLM trước, fallback về extractive.
    """
    context = _build_context(chunks, policy_result)
    sources = list(dict.fromkeys(c.get("source", "unknown") for c in chunks))

    # Build messages for LLM
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Cau hoi: {task}\n\n"
                f"{context}\n\n"
                "Hay tra loi cau hoi dua vao tai lieu tren. "
                "Trich dan nguon [ten_file] sau moi thong tin quan trong."
            ),
        },
    ]

    answer = _call_llm(messages)

    # Fallback to extractive if LLM unavailable or returned empty
    if not answer or answer.startswith("[SYNTHESIS ERROR]"):
        answer = _synthesize_extractive(task, chunks, policy_result)

    confidence = _estimate_confidence(chunks, answer, policy_result)

    return {
        "answer": answer,
        "sources": sources,
        "confidence": confidence,
    }


# ─────────────────────────────────────────────
# Worker Entry Point
# ─────────────────────────────────────────────

def run(state: dict) -> dict:
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
# Standalone Test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    print("=" * 50)
    print("Synthesis Worker — Standalone Test")
    print("=" * 50)

    test1 = {
        "task": "SLA ticket P1 la bao lau?",
        "retrieved_chunks": [
            {
                "text": "Ticket P1: Phan hoi ban dau 15 phut. Xu ly va khac phuc 4 gio. Escalation: tu dong len Senior Engineer neu khong co phan hoi trong 10 phut.",
                "source": "sla_p1_2026.txt",
                "score": 0.92,
            }
        ],
        "policy_result": {},
    }
    result1 = run(test1.copy())
    print(f"\nTest 1 — SLA query:")
    print(f"  Confidence: {result1['confidence']}")
    print(f"  Answer: {result1['final_answer'][:200]}")

    test2 = {
        "task": "Khach hang Flash Sale yeu cau hoan tien vi loi nha san xuat.",
        "retrieved_chunks": [
            {
                "text": "Ngoai le: Don hang Flash Sale khong duoc hoan tien theo Dieu 3 chinh sach v4.",
                "source": "policy_refund_v4.txt",
                "score": 0.88,
            }
        ],
        "policy_result": {
            "policy_applies": False,
            "exceptions_found": [
                {
                    "type": "flash_sale_exception",
                    "rule": "Don hang Flash Sale khong duoc hoan tien (Dieu 3, chinh sach v4).",
                    "source": "policy_refund_v4.txt",
                }
            ],
        },
    }
    result2 = run(test2.copy())
    print(f"\nTest 2 — Flash Sale exception:")
    print(f"  Confidence: {result2['confidence']}")
    print(f"  Answer: {result2['final_answer'][:300]}")

    print("\n[OK] synthesis_worker test done.")
