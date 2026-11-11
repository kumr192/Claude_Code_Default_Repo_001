"""Claude Code PreToolUse hook: asks the Orbit server before each tool call.

Safe steps are allowed at once. Risky steps wait until you approve or deny
them in the app. Uses only the Python standard library.
"""

import json
import os
import sys
import time
import urllib.request


def call(path: str, body: dict | None = None) -> dict:
    url = os.environ["ORBIT_URL"].rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Authorization", "Bearer " + os.environ["ORBIT_TOKEN"])
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def decide(decision: str, reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main() -> None:
    event = json.load(sys.stdin)
    try:
        res = call("/api/hook/check", {
            "chat_id": int(os.environ.get("ORBIT_CHAT_ID", "0")),
            "tool": event.get("tool_name", ""),
            "input": event.get("tool_input", {}),
        })
        if res["decision"] == "allow":
            decide("allow", "Orbit: safe step")
        approval_id = res["approval_id"]
        deadline = time.time() + res.get("timeout", 900)
        while time.time() < deadline:
            status = call(f"/api/approvals/{approval_id}")["status"]
            if status == "approved":
                decide("allow", "Approved by the user in Orbit")
            if status == "denied":
                decide("deny", "The user denied this step in Orbit. Do not retry it; ask what to do instead.")
            time.sleep(2)
        decide("deny", "No approval in time. Ask the user before trying again.")
    except Exception as e:  # if the server is down, fail safe
        decide("deny", f"Orbit approval check failed: {e}")


if __name__ == "__main__":
    main()
