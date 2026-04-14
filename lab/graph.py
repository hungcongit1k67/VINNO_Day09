"""
graph.py — Supervisor Orchestrator
Sprint 1: Supervisor-Worker pattern với routing logic rõ ràng.

Kiến trúc:
    Input → Supervisor → [retrieval_worker | policy_tool_worker | human_review]
                       → synthesis_worker → Output

Chạy thử:
    python graph.py
"""

import json
import os
import sys
from datetime import datetime
from typing import TypedDict, Literal, Optional

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ─────────────────────────────────────────────
# 1. Shared State
# ─────────────────────────────────────────────

class AgentState(TypedDict):
    # Input
    task: str

    # Supervisor decisions
    route_reason: str
    risk_high: bool
    needs_tool: bool
    hitl_triggered: bool

    # Worker outputs
    retrieved_chunks: list
    retrieved_sources: list
    policy_result: dict
    mcp_tools_used: list
    worker_io_logs: list

    # Final output
    final_answer: str
    sources: list
    confidence: float

    # Trace
    history: list
    workers_called: list
    supervisor_route: str
    latency_ms: Optional[int]
    run_id: str


def make_initial_state(task: str) -> AgentState:
    return {
        "task": task,
        "route_reason": "",
        "risk_high": False,
        "needs_tool": False,
        "hitl_triggered": False,
        "retrieved_chunks": [],
        "retrieved_sources": [],
        "policy_result": {},
        "mcp_tools_used": [],
        "worker_io_logs": [],
        "final_answer": "",
        "sources": [],
        "confidence": 0.0,
        "history": [],
        "workers_called": [],
        "supervisor_route": "",
        "latency_ms": None,
        "run_id": f"run_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:20]}",
    }


# ─────────────────────────────────────────────
# 2. Supervisor Node
# ─────────────────────────────────────────────

# Routing keyword sets
_POLICY_KW = [
    "hoàn tiền", "refund", "flash sale", "license key", "license",
    "subscription", "store credit", "điều 3", "chính sách hoàn",
    "cấp quyền", "access level", "level 2", "level 3", "level 4",
    "quyền truy cập", "emergency access", "contractor", "cấp phép",
]
_SLA_KW = [
    "p1", "sla", "ticket", "escalation", "sự cố", "incident",
    "on-call", "oncall", "severity", "pagerduty",
]
_RISK_KW = [
    "emergency", "khẩn cấp", "2am", "3am", "midnight",
    "không rõ", "err-", "unknown error",
]
_MULTIHOP_KW = [
    "đồng thời", "cả hai", "cả hai quy trình", "và cũng",
    "song song", "nêu đủ",
]


def supervisor_node(state: AgentState) -> AgentState:
    """
    Supervisor phân tích task và quyết định route.
    Quy tắc:
      - policy/access keywords → policy_tool_worker (có MCP)
      - SLA/P1/ticket keywords → retrieval_worker
      - ERR-xxx không có context → human_review
      - multi-hop → policy_tool_worker (cần cross-doc retrieval)
      - còn lại → retrieval_worker
    """
    task = state["task"].lower()
    state["history"].append(f"[supervisor] task: {state['task'][:80]}")

    route = "retrieval_worker"
    route_reason = "default: câu hỏi retrieval thông thường"
    needs_tool = False
    risk_high = False

    # Detect risk flags
    if any(kw in task for kw in _RISK_KW):
        risk_high = True

    # Detect multi-hop (needs both docs)
    is_multihop = any(kw in task for kw in _MULTIHOP_KW)

    # Routing logic
    has_policy_kw = any(kw in task for kw in _POLICY_KW)
    has_sla_kw = any(kw in task for kw in _SLA_KW)

    if has_policy_kw and has_sla_kw:
        # Cross-document query (e.g., access + SLA P1)
        route = "policy_tool_worker"
        route_reason = "multi-hop: task chứa cả policy/access keyword VÀ SLA/P1 keyword → cần cross-doc retrieval"
        needs_tool = True
    elif is_multihop:
        route = "policy_tool_worker"
        route_reason = "multi-hop signal detected (đồng thời/cả hai quy trình) → policy_tool_worker với MCP"
        needs_tool = True
    elif has_policy_kw:
        route = "policy_tool_worker"
        matched = [kw for kw in _POLICY_KW if kw in task]
        route_reason = f"task chứa policy/access keyword: {matched[:3]}"
        needs_tool = True
    elif has_sla_kw:
        route = "retrieval_worker"
        matched = [kw for kw in _SLA_KW if kw in task]
        route_reason = f"task chứa SLA/incident keyword: {matched[:3]}"
    else:
        route = "retrieval_worker"
        route_reason = "default: không khớp policy/SLA keyword → retrieval_worker"

    # Human review override: unknown error code with no context
    if risk_high and "err-" in task and not has_sla_kw and not has_policy_kw:
        route = "human_review"
        route_reason = "unknown error code (ERR-xxx) + risk_high → escalate to human review"

    # Append risk flag to reason
    if risk_high:
        route_reason += " | risk_high=True (emergency/khẩn cấp/lúc 2am)"

    state["supervisor_route"] = route
    state["route_reason"] = route_reason
    state["needs_tool"] = needs_tool
    state["risk_high"] = risk_high
    state["history"].append(
        f"[supervisor] route={route} | needs_tool={needs_tool} | risk_high={risk_high}"
    )
    state["history"].append(f"[supervisor] route_reason: {route_reason}")
    return state


# ─────────────────────────────────────────────
# 3. Route Decision
# ─────────────────────────────────────────────

def route_decision(state: AgentState) -> Literal["retrieval_worker", "policy_tool_worker", "human_review"]:
    return state.get("supervisor_route", "retrieval_worker")  # type: ignore


# ─────────────────────────────────────────────
# 4. Human Review Node (HITL placeholder)
# ─────────────────────────────────────────────

def human_review_node(state: AgentState) -> AgentState:
    state["hitl_triggered"] = True
    state["workers_called"].append("human_review")
    state["history"].append("[human_review] HITL triggered — awaiting human input")
    print(f"\n[HITL] Task requires human review: {state['task'][:60]}")
    print(f"       Reason: {state['route_reason']}")
    print(f"       Auto-approving in lab mode.\n")
    # After approval, fall through to retrieval
    state["supervisor_route"] = "retrieval_worker"
    state["route_reason"] += " | human approved → retrieval"
    return state


# ─────────────────────────────────────────────
# 5. Worker imports
# ─────────────────────────────────────────────

from workers.retrieval import run as retrieval_run
from workers.policy_tool import run as policy_tool_run
from workers.synthesis import run as synthesis_run


def retrieval_worker_node(state: AgentState) -> AgentState:
    """Gọi retrieval worker thực."""
    return retrieval_run(state)


def policy_tool_worker_node(state: AgentState) -> AgentState:
    """Gọi policy/tool worker thực."""
    return policy_tool_run(state)


def synthesis_worker_node(state: AgentState) -> AgentState:
    """Gọi synthesis worker thực."""
    return synthesis_run(state)


# ─────────────────────────────────────────────
# 6. Build Graph (Python-native orchestrator)
# ─────────────────────────────────────────────

def build_graph():
    """
    Supervisor-Worker graph (Python-native, không cần LangGraph).

    Flow:
      supervisor → route_decision → {
        retrieval_worker  → synthesis_worker → END
        policy_tool_worker → retrieval (nếu cần thêm context) → synthesis_worker → END
        human_review → retrieval_worker → synthesis_worker → END
      }
    """
    def run(state: AgentState) -> AgentState:
        import time
        start = time.time()

        # Step 1: Supervisor decides route
        state = supervisor_node(state)
        route = route_decision(state)

        # Step 2: Route to appropriate worker(s)
        if route == "human_review":
            state = human_review_node(state)
            state = retrieval_worker_node(state)
            state = synthesis_worker_node(state)

        elif route == "policy_tool_worker":
            # Always retrieve first to give policy worker grounded context
            state = retrieval_worker_node(state)
            # Then check policy + MCP tools
            state = policy_tool_worker_node(state)
            # Synthesize
            state = synthesis_worker_node(state)

        else:
            # Default: retrieval → synthesis
            state = retrieval_worker_node(state)
            state = synthesis_worker_node(state)

        state["latency_ms"] = int((time.time() - start) * 1000)
        state["history"].append(f"[graph] completed in {state['latency_ms']}ms")
        return state

    return run


# ─────────────────────────────────────────────
# 7. Public API
# ─────────────────────────────────────────────

_graph = build_graph()


def run_graph(task: str) -> AgentState:
    """Entry point: nhận câu hỏi, trả về AgentState với full trace."""
    state = make_initial_state(task)
    return _graph(state)


def save_trace(state: AgentState, output_dir: str = "./artifacts/traces") -> str:
    """Lưu trace ra file JSON."""
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{output_dir}/{state['run_id']}.json"
    # Serialize: convert any non-serializable types
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, default=str)
    return filename


# ─────────────────────────────────────────────
# 8. Manual Test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    print("=" * 65)
    print("Day 09 Lab — Supervisor-Worker Graph")
    print("=" * 65)

    test_queries = [
        "SLA xử lý ticket P1 là bao lâu?",
        "Khách hàng Flash Sale yêu cầu hoàn tiền vì sản phẩm lỗi — được không?",
        "Cần cấp quyền Level 3 để khắc phục P1 khẩn cấp. Quy trình là gì?",
    ]

    os.makedirs("artifacts/traces", exist_ok=True)

    for query in test_queries:
        print(f"\n[Query] {query}")
        result = run_graph(query)
        print(f"  Route   : {result['supervisor_route']}")
        print(f"  Reason  : {result['route_reason']}")
        print(f"  Workers : {result['workers_called']}")
        print(f"  MCP     : {[t.get('tool') for t in result.get('mcp_tools_used', [])]}")
        print(f"  Chunks  : {len(result.get('retrieved_chunks', []))}")
        print(f"  Sources : {result.get('retrieved_sources', [])}")
        answer = result.get('final_answer', '')
        print(f"  Answer  : {answer[:120]}...")
        print(f"  Conf    : {result['confidence']}")
        print(f"  Latency : {result['latency_ms']}ms")

        trace_file = save_trace(result)
        print(f"  Trace   : {trace_file}")

    print("\n[OK] graph.py test complete.")
