"""
workers/policy_tool.py — Policy & Tool Worker
Sprint 2+3: Kiểm tra policy dựa vào context, gọi MCP tools khi cần.

Input:
  - task: câu hỏi
  - retrieved_chunks: context từ retrieval_worker
  - needs_tool: True → được phép gọi MCP

Output:
  - policy_result: {policy_applies, policy_name, exceptions_found, source, ...}
  - mcp_tools_used: list of MCP tool calls với timestamp
"""

import os
import sys
from datetime import datetime
from typing import Optional

WORKER_NAME = "policy_tool_worker"


# ─────────────────────────────────────────────
# MCP Client — gọi dispatch_tool từ mcp_server
# ─────────────────────────────────────────────

def _call_mcp_tool(tool_name: str, tool_input: dict) -> dict:
    """
    Gọi MCP tool qua dispatch_tool().
    Log đầy đủ: tool, input, output, error, timestamp.
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        from mcp_server import dispatch_tool
        result = dispatch_tool(tool_name, tool_input)
        return {
            "tool": tool_name,
            "input": tool_input,
            "output": result,
            "error": None,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "tool": tool_name,
            "input": tool_input,
            "output": None,
            "error": {"code": "MCP_CALL_FAILED", "reason": str(e)},
            "timestamp": datetime.now().isoformat(),
        }


# ─────────────────────────────────────────────
# Access Level Extractor
# ─────────────────────────────────────────────

def _extract_access_level(task: str) -> Optional[int]:
    """Trích xuất access level từ task text."""
    task_lower = task.lower()
    for level in [4, 3, 2, 1]:
        if f"level {level}" in task_lower or f"l{level}" in task_lower:
            return level
    if "admin access" in task_lower:
        return 3  # admin = level 3 in SOP
    return None


def _extract_requester_role(task: str) -> str:
    """Trích xuất vai trò người yêu cầu từ task text."""
    task_lower = task.lower()
    if "contractor" in task_lower:
        return "contractor"
    if "senior engineer" in task_lower:
        return "senior_engineer"
    if "team lead" in task_lower:
        return "team_lead"
    if "dev" in task_lower or "engineer" in task_lower:
        return "engineer"
    return "employee"


# ─────────────────────────────────────────────
# Rule-based Policy Analysis
# ─────────────────────────────────────────────

def analyze_policy(task: str, chunks: list) -> dict:
    """
    Phân tích policy dựa trên context chunks.

    Xử lý exceptions:
    - Flash Sale → không được hoàn tiền
    - Digital product / license key / subscription → không được hoàn tiền
    - Sản phẩm đã kích hoạt → không được hoàn tiền
    - Đơn trước 01/02/2026 → áp dụng policy v3 (flag cho synthesis)
    """
    task_lower = task.lower()

    exceptions_found = []

    # Chỉ detect exceptions khi task là yêu cầu/câu hỏi về một trường hợp cụ thể,
    # không phải câu hỏi chung về policy rules (tránh false positive).
    is_specific_case = any(kw in task_lower for kw in [
        "co duoc", "được không", "co the", "có thể", "yeu cau", "yêu cầu",
        "don hang", "đơn hàng", "san pham", "sản phẩm", "khi", "neu", "nếu",
        "cho phep", "cho phép", "ap dung", "áp dụng",
    ])

    # Exception 1: Flash Sale — CHỈ detect từ task (không từ context)
    # context_text thường chứa Flash Sale clause của policy doc => false positive
    if "flash sale" in task_lower:
        exceptions_found.append({
            "type": "flash_sale_exception",
            "rule": "Don hang Flash Sale khong duoc hoan tien (Dieu 3, chinh sach v4).",
            "source": "policy_refund_v4.txt",
        })

    # Exception 2: Digital product / license (detect từ task)
    if any(kw in task_lower for kw in ["license key", "license", "subscription", "ky thuat so", "kỹ thuật số"]):
        if is_specific_case:
            exceptions_found.append({
                "type": "digital_product_exception",
                "rule": "San pham ky thuat so (license key, subscription) khong duoc hoan tien (Dieu 3).",
                "source": "policy_refund_v4.txt",
            })

    # Exception 3: Activated product
    if any(kw in task_lower for kw in ["da kich hoat", "đã kích hoạt", "da su dung", "da dang ky"]):
        exceptions_found.append({
            "type": "activated_exception",
            "rule": "San pham da kich hoat hoac da su dung khong duoc hoan tien (Dieu 3).",
            "source": "policy_refund_v4.txt",
        })

    policy_applies = len(exceptions_found) == 0
    policy_name = "refund_policy_v4"

    # Temporal scoping: đơn trước 01/02/2026
    policy_version_note = ""
    if any(kw in task_lower for kw in ["31/01", "30/01", "truoc 01/02", "trước 01/02", "01/2026"]):
        policy_version_note = (
            "Don hang dat truoc 01/02/2026 ap dung chinh sach hoan tien phien ban 3 "
            "(khong co trong tai lieu hien tai). Can xac nhan voi CS Team ve noi dung chinh sach v3."
        )

    sources = list(dict.fromkeys(c.get("source", "unknown") for c in chunks if c))

    return {
        "policy_applies": policy_applies,
        "policy_name": policy_name,
        "exceptions_found": exceptions_found,
        "source": sources,
        "policy_version_note": policy_version_note,
        "explanation": "Rule-based policy analysis with exception detection.",
    }


# ─────────────────────────────────────────────
# Worker Entry Point
# ─────────────────────────────────────────────

def run(state: dict) -> dict:
    """
    Worker entry point — gọi từ graph.py.

    Flow:
      1. Nếu needs_tool + chưa có chunks → gọi MCP search_kb
      2. Phân tích policy exceptions từ chunks
      3. Gọi MCP check_access_permission nếu task liên quan access/quyền
      4. Gọi MCP get_ticket_info nếu task liên quan ticket P1
    """
    task = state.get("task", "")
    task_lower = task.lower()
    chunks = state.get("retrieved_chunks", [])
    needs_tool = state.get("needs_tool", False)

    state.setdefault("workers_called", [])
    state.setdefault("history", [])
    state.setdefault("mcp_tools_used", [])
    state["workers_called"].append(WORKER_NAME)

    worker_io = {
        "worker": WORKER_NAME,
        "input": {
            "task": task,
            "chunks_count": len(chunks),
            "needs_tool": needs_tool,
        },
        "output": None,
        "error": None,
    }

    try:
        # ── Step 1: MCP search_kb nếu chưa có chunks ──
        if not chunks and needs_tool:
            mcp_r = _call_mcp_tool("search_kb", {"query": task, "top_k": 5})
            state["mcp_tools_used"].append(mcp_r)
            state["history"].append(f"[{WORKER_NAME}] MCP search_kb called (no prior chunks)")
            if mcp_r.get("output") and mcp_r["output"].get("chunks"):
                chunks = mcp_r["output"]["chunks"]
                state["retrieved_chunks"] = chunks
                state["retrieved_sources"] = mcp_r["output"].get("sources", [])

        # ── Step 2: Policy analysis ──
        policy_result = analyze_policy(task, chunks)
        state["policy_result"] = policy_result

        # ── Step 3: MCP check_access_permission ──
        # Gọi khi task liên quan cấp quyền / access level
        is_access_query = any(kw in task_lower for kw in [
            "cap quyen", "cấp quyền", "access", "level 2", "level 3", "level 4",
            "quyen truy cap", "quyền truy cập", "contractor", "emergency access",
        ])
        if needs_tool and is_access_query:
            level = _extract_access_level(task)
            role = _extract_requester_role(task)
            is_emergency = any(kw in task_lower for kw in [
                "emergency", "khan cap", "khẩn cấp", "p1", "2am", "3am",
            ])
            if level:
                mcp_r = _call_mcp_tool("check_access_permission", {
                    "access_level": level,
                    "requester_role": role,
                    "is_emergency": is_emergency,
                })
                state["mcp_tools_used"].append(mcp_r)
                state["history"].append(
                    f"[{WORKER_NAME}] MCP check_access_permission: level={level}, "
                    f"role={role}, emergency={is_emergency}"
                )
                # Augment policy_result with access check data
                if mcp_r.get("output") and not mcp_r["output"].get("error"):
                    acc = mcp_r["output"]
                    policy_result["access_check"] = {
                        "can_grant": acc.get("can_grant"),
                        "required_approvers": acc.get("required_approvers", []),
                        "emergency_override": acc.get("emergency_override", False),
                        "notes": acc.get("notes", []),
                    }
                    state["policy_result"] = policy_result

        # ── Step 4: MCP get_ticket_info ──
        # Gọi khi task hỏi về ticket P1 cụ thể
        is_ticket_query = any(kw in task_lower for kw in ["ticket", "p1", "jira", "it-"])
        if needs_tool and is_ticket_query:
            mcp_r = _call_mcp_tool("get_ticket_info", {"ticket_id": "P1-LATEST"})
            state["mcp_tools_used"].append(mcp_r)
            state["history"].append(f"[{WORKER_NAME}] MCP get_ticket_info: P1-LATEST")

        worker_io["output"] = {
            "policy_applies": policy_result["policy_applies"],
            "exceptions_count": len(policy_result.get("exceptions_found", [])),
            "mcp_calls": len(state["mcp_tools_used"]),
            "access_check": bool(policy_result.get("access_check")),
        }
        state["history"].append(
            f"[{WORKER_NAME}] policy_applies={policy_result['policy_applies']}, "
            f"exceptions={len(policy_result.get('exceptions_found', []))}, "
            f"mcp_calls={len(state['mcp_tools_used'])}"
        )

    except Exception as e:
        worker_io["error"] = {"code": "POLICY_CHECK_FAILED", "reason": str(e)}
        state["policy_result"] = {"error": str(e)}
        state["history"].append(f"[{WORKER_NAME}] ERROR: {e}")

    state.setdefault("worker_io_logs", []).append(worker_io)
    return state


# ─────────────────────────────────────────────
# Standalone Test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    print("=" * 55)
    print("Policy Tool Worker — Standalone Test")
    print("=" * 55)

    cases = [
        {
            "task": "Khach hang Flash Sale yeu cau hoan tien vi san pham loi — duoc khong?",
            "retrieved_chunks": [
                {"text": "Ngoai le: Don hang Flash Sale khong duoc hoan tien.", "source": "policy_refund_v4.txt", "score": 0.9}
            ],
            "needs_tool": True,
        },
        {
            "task": "Contractor can cap Level 3 access de sua P1 khan cap. Quy trinh?",
            "retrieved_chunks": [
                {"text": "Level 3 — Elevated Access: Phe duyet: Line Manager + IT Admin + IT Security.", "source": "access_control_sop.txt", "score": 0.88}
            ],
            "needs_tool": True,
        },
    ]

    for tc in cases:
        print(f"\nTask: {tc['task'][:70]}")
        result = run(tc.copy())
        pr = result.get("policy_result", {})
        print(f"  policy_applies: {pr.get('policy_applies')}")
        for ex in pr.get("exceptions_found", []):
            print(f"  exception: {ex['type']}")
        acc = pr.get("access_check")
        if acc:
            print(f"  access_check: can_grant={acc.get('can_grant')}, "
                  f"approvers={acc.get('required_approvers')}")
        print(f"  MCP calls: {len(result.get('mcp_tools_used', []))}")
        for m in result.get("mcp_tools_used", []):
            print(f"    - {m['tool']}")

    print("\n[OK] policy_tool_worker test done.")
