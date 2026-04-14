"""
single_agent_rag.py — Single Agent RAG baseline (Day 08 style)

Kiến trúc đơn giản: 1 agent duy nhất
    Input → embed → ChromaDB retrieve (top_k=3) → extractive synthesis → Output

Không có:
  - Supervisor / routing logic
  - MCP tool calls
  - HITL
  - Policy analysis

Dùng để so sánh với Day 09 multi-agent trong compare_single_vs_multi().

Chạy:
    python single_agent_rag.py                              # test_questions.json
    python single_agent_rag.py --questions data/grading_questions.json

Output:
    artifacts/day08_baseline.json    — metrics summary (input cho compare_single_vs_multi)
    artifacts/day08_traces/          — trace JSON từng câu
"""

import json
import os
import sys
import time
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from workers.retrieval import retrieve_dense
from workers.synthesis import synthesize


# ─────────────────────────────────────────────
# 1. Single Agent — một lần chạy
# ─────────────────────────────────────────────

def run_single_agent(question: str) -> dict:
    """
    Single agent RAG: retrieve → synthesize.
    Không có routing, không MCP, không HITL.

    Returns:
        dict trace với answer, sources, confidence, latency_ms
    """
    start = time.time()

    # Step 1: Retrieve (dùng lại retrieval worker, bỏ qua supervisor)
    chunks = retrieve_dense(question, top_k=3)
    sources = list(dict.fromkeys(c["source"] for c in chunks))

    # Step 2: Synthesize (không có policy_result — single agent không check policy)
    result = synthesize(question, chunks, policy_result={})

    latency_ms = int((time.time() - start) * 1000)

    return {
        "question": question,
        "answer": result["answer"],
        "sources": result["sources"],
        "confidence": result["confidence"],
        "latency_ms": latency_ms,
        "chunks_retrieved": len(chunks),
        "workers_called": ["retrieval_worker", "synthesis_worker"],
        "supervisor_route": "N/A",
        "mcp_tools_used": [],
        "hitl_triggered": False,
        "policy_check": False,
    }


# ─────────────────────────────────────────────
# 2. Chạy toàn bộ questions
# ─────────────────────────────────────────────

def run_all(
    questions_file: str = "data/grading_questions.json",
    traces_dir: str = "artifacts/day08_traces",
) -> dict:
    """
    Chạy single agent RAG trên toàn bộ câu hỏi.

    Returns:
        summary dict tương thích với compare_single_vs_multi()
    """
    with open(questions_file, encoding="utf-8") as f:
        questions = json.load(f)

    os.makedirs(traces_dir, exist_ok=True)

    results = []
    confidences = []
    latencies = []
    abstain_count = 0
    source_counts = {}

    # Multi-hop questions = có expected_sources từ 2+ docs HOẶC test_type multi_worker*
    multi_hop_qs = [
        q for q in questions
        if q.get("test_type") in ("multi_worker", "multi_worker_multi_doc")
        or len(q.get("expected_sources", [])) >= 2
    ]
    multi_hop_correct = 0

    print(f"\n[Single Agent RAG] Running {len(questions)} questions")
    print(f"   Source: {questions_file}")
    print("=" * 60)

    for i, q in enumerate(questions, 1):
        q_id = q.get("id", f"q{i:02d}")
        question_text = q["question"]
        print(f"[{i:02d}/{len(questions)}] {q_id}: {question_text[:65]}...")

        result = run_single_agent(question_text)
        result["id"] = q_id
        result["expected_sources"] = q.get("expected_sources", [])
        result["expected_answer"] = q.get("expected_answer", "")
        result["test_type"] = q.get("test_type", "single_worker")
        result["category"] = q.get("category", "")
        result["difficulty"] = q.get("difficulty", "")

        conf = result["confidence"]
        lat = result["latency_ms"]

        if conf > 0:
            confidences.append(conf)
        latencies.append(lat)

        # Abstain: confidence thấp HOẶC không có sources
        is_abstain = conf < 0.3 or not result["sources"]
        result["abstained"] = is_abstain
        if is_abstain:
            abstain_count += 1

        # Multi-hop accuracy: expected_sources ⊆ actual_sources
        if q in multi_hop_qs:
            expected = set(q.get("expected_sources", []))
            actual = set(result["sources"])
            hit = bool(expected) and expected.issubset(actual)
            result["multi_hop_hit"] = hit
            if hit:
                multi_hop_correct += 1

        # Source coverage
        for src in result["sources"]:
            source_counts[src] = source_counts.get(src, 0) + 1

        print(f"  conf={conf:.2f} | {lat}ms | sources={result['sources']} "
              f"{'[abstain]' if is_abstain else ''}")

        # Save trace
        trace_path = os.path.join(traces_dir, f"{q_id}.json")
        with open(trace_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        results.append(result)

    # ── Compute summary metrics ──
    total = len(questions)
    n_multi = len(multi_hop_qs)

    summary = {
        "generated_at": datetime.now().isoformat(),
        "agent_type": "single_agent_rag",
        "description": (
            "Day 08 style: embed → retrieve_top3 → extractive_synthesis. "
            "Không có supervisor, routing, MCP tools, HITL."
        ),
        "questions_file": questions_file,
        "total_questions": total,
        "avg_confidence": round(sum(confidences) / len(confidences), 3) if confidences else 0,
        "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else 0,
        "abstain_rate": (
            f"{abstain_count}/{total} "
            f"({100 * abstain_count // total}%)" if total else "0%"
        ),
        "multi_hop_accuracy": (
            f"{multi_hop_correct}/{n_multi} "
            f"({100 * multi_hop_correct // n_multi}%)" if n_multi else "0/0 (N/A)"
        ),
        "routing_distribution": {
            "retrieval_worker+synthesis_worker": f"{total}/{total} (100%)"
        },
        "mcp_usage_rate": f"0/{total} (0%)",
        "hitl_rate": f"0/{total} (0%)",
        "top_sources": sorted(source_counts.items(), key=lambda x: -x[1])[:5],
    }

    return summary, results


# ─────────────────────────────────────────────
# 3. CLI
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    parser = argparse.ArgumentParser(description="Single Agent RAG — Day 08 baseline")
    parser.add_argument(
        "--questions",
        default="data/test_questions.json",
        help="Path to questions JSON file",
    )
    args = parser.parse_args()

    summary, results = run_all(args.questions)

    os.makedirs("artifacts", exist_ok=True)
    out_path = "artifacts/day08_baseline.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("Single Agent RAG — Summary")
    print("=" * 60)
    skip = {"generated_at", "description", "questions_file", "top_sources"}
    for k, v in summary.items():
        if k not in skip:
            print(f"  {k}: {v}")

    print(f"\n  top_sources:")
    for src, cnt in summary.get("top_sources", []):
        print(f"    {src}: {cnt} lần")

    print(f"\nBaseline saved → {out_path}")
    print("Chạy compare:\n  python eval_trace.py --compare")
