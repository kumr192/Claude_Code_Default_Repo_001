"""Runs one chat turn through the official Claude Code CLI or Codex CLI.

Both CLIs use the subscription you signed in with on the VM.
This code never reads, stores or sends your login tokens.
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

from . import db

CLAUDE_BIN = os.environ.get("ORBIT_CLAUDE_BIN", "claude")
CODEX_BIN = os.environ.get("ORBIT_CODEX_BIN", "codex")
HOOK_SCRIPT = Path(__file__).with_name("hook.py")

SYSTEM_PROMPT = """You are Orbit, a personal agent running on the user's own Linux cloud computer.
You can run shell commands, write and run code, and use the browser tools (Playwright)
to browse the web and sign in to sites. The browser is visible on the computer's desktop,
and the user can take over at any time. Work in the current folder unless told otherwise.
When a site needs a login, 2FA or a captcha, stop and ask the user to do it in the live
computer view, then continue. Keep final answers short and clear."""

LIMIT_WORDS = re.compile(r"usage limit|rate limit|limit reached|hit your limit|quota|429|overloaded", re.I)


def split_model(choice: str) -> tuple[str, str]:
    """'claude:opus' -> ('claude', 'opus')."""
    provider, _, model = choice.partition(":")
    return provider, model


def history_prefix(chat_id: int, limit: int = 12) -> str:
    """Recent chat text, so a model that joins mid-chat knows what happened."""
    rows = db.q(
        "SELECT role, content FROM messages WHERE chat_id=? AND role IN ('user','assistant') "
        "ORDER BY id DESC LIMIT ?", chat_id, limit,
    )
    if not rows:
        return ""
    lines = [f"{r['role'].upper()}: {r['content'][:2000]}" for r in reversed(rows)]
    return "Earlier conversation (for context):\n" + "\n\n".join(lines) + "\n\nNew message:\n"


def short(value, n: int = 300) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= n else text[:n] + "…"


async def run_turn(chat_id: int, text: str, choice: str, cfg: dict, server_url: str) -> None:
    """Run one user message. Handles 'auto' fallback from Claude to Codex."""
    db.run("UPDATE chats SET running=1 WHERE id=?", chat_id)
    try:
        if choice == "auto":
            ok, limited = await _run(chat_id, text, cfg["auto_primary"], cfg, server_url)
            if not ok and limited:
                db.add_message(chat_id, "system", f"Claude hit its usage limit. Switching to {cfg['auto_fallback']}.")
                await _run(chat_id, text, cfg["auto_fallback"], cfg, server_url)
        else:
            await _run(chat_id, text, choice, cfg, server_url)
    except Exception as e:  # keep the server alive and show the error in the chat
        db.add_message(chat_id, "error", f"{type(e).__name__}: {e}")
    finally:
        db.run("UPDATE chats SET running=0 WHERE id=?", chat_id)


async def _run(chat_id, text, choice, cfg, server_url) -> tuple[bool, bool]:
    provider, model = split_model(choice)
    chat = db.one("SELECT * FROM chats WHERE id=?", chat_id)
    # If the other provider did the earlier turns, give this one the history.
    prompt = text
    if chat["last_provider"] and chat["last_provider"] != provider:
        prompt = history_prefix(chat_id) + text
    db.run("UPDATE chats SET last_provider=? WHERE id=?", provider, chat_id)
    if provider == "claude":
        return await _run_claude(chat, prompt, model, cfg, server_url)
    if provider == "codex":
        return await _run_codex(chat, prompt, model, cfg)
    db.add_message(chat_id, "error", f"Unknown model choice: {choice}")
    return False, False


async def _stream(cmd: list[str], cwd: str, env: dict):
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd, env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=16 * 1024 * 1024,
    )
    async for raw in proc.stdout:
        line = raw.decode(errors="replace").strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            yield {"type": "_text", "text": line}
    err = (await proc.stderr.read()).decode(errors="replace").strip()
    code = await proc.wait()
    yield {"type": "_exit", "code": code, "stderr": err}


async def _run_claude(chat, prompt, model, cfg, server_url) -> tuple[bool, bool]:
    chat_id = chat["id"]
    label = f"claude:{model}"
    settings = {
        "hooks": {
            "PreToolUse": [{
                "matcher": "*",
                "hooks": [{
                    "type": "command",
                    "command": f"{sys.executable} {HOOK_SCRIPT}",
                    "timeout": int(cfg["approval_timeout"]) + 30,
                }],
            }]
        }
    }
    mcp = {"mcpServers": {"playwright": {"command": "playwright-mcp", "args": ["--browser", "chrome"]}}}
    cmd = [
        CLAUDE_BIN, "-p", prompt,
        "--output-format", "stream-json", "--verbose",
        "--settings", json.dumps(settings),
        "--mcp-config", json.dumps(mcp),
        "--append-system-prompt", SYSTEM_PROMPT,
        # The VM is the sandbox. Risky steps are still stopped by the
        # approval hook above, which runs even in this mode.
        "--permission-mode", "bypassPermissions",
    ]
    if model:
        cmd += ["--model", model]
    if chat["claude_session"]:
        cmd += ["--resume", chat["claude_session"]]

    env = {**os.environ, "ORBIT_URL": server_url, "ORBIT_TOKEN": cfg["token"], "ORBIT_CHAT_ID": str(chat_id)}
    # Make sure an API key can never be used by mistake: subscription only.
    env.pop("ANTHROPIC_API_KEY", None)

    ok, limited, got_text = True, False, False
    async for ev in _stream(cmd, cfg["workspace"], env):
        t = ev.get("type")
        if t == "system" and ev.get("session_id"):
            db.run("UPDATE chats SET claude_session=? WHERE id=?", ev["session_id"], chat_id)
        elif t == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "text" and block.get("text", "").strip():
                    db.add_message(chat_id, "assistant", block["text"], label)
                    got_text = True
                elif block.get("type") == "tool_use":
                    db.add_message(chat_id, "tool", f"{block.get('name')}  {short(block.get('input'))}", label)
        elif t == "result":
            if ev.get("session_id"):
                db.run("UPDATE chats SET claude_session=? WHERE id=?", ev["session_id"], chat_id)
            if ev.get("is_error"):
                ok = False
                msg = str(ev.get("result") or ev.get("subtype") or "Claude returned an error")
                limited = bool(LIMIT_WORDS.search(msg))
                db.add_message(chat_id, "error", msg, label)
            elif not got_text and ev.get("result"):
                db.add_message(chat_id, "assistant", ev["result"], label)
        elif t == "_text":
            if LIMIT_WORDS.search(ev["text"]):
                limited = True
        elif t == "_exit" and ev["code"] != 0:
            ok = False
            limited = limited or bool(LIMIT_WORDS.search(ev["stderr"]))
            if ev["stderr"]:
                db.add_message(chat_id, "error", short(ev["stderr"], 1500), label)
    return ok, limited


async def _run_codex(chat, prompt, model, cfg) -> tuple[bool, bool]:
    chat_id = chat["id"]
    label = f"codex:{model or 'default'}"
    opts = [
        "--json", "--skip-git-repo-check",
        # Codex works inside the workspace folder, with internet access.
        "-c", 'sandbox_mode="workspace-write"',
        "-c", "sandbox_workspace_write.network_access=true",
        "-c", 'approval_policy="never"',
    ]
    if model and model != "default":
        opts += ["-m", model]
    if chat["codex_session"]:
        cmd = [CODEX_BIN, "exec", "resume", *opts, chat["codex_session"], prompt]
    else:
        cmd = [CODEX_BIN, "exec", *opts, prompt]

    env = {**os.environ}
    # Subscription only: never fall back to an OpenAI API key.
    env.pop("OPENAI_API_KEY", None)
    env.pop("CODEX_API_KEY", None)

    ok, limited = True, False
    async for ev in _stream(cmd, cfg["workspace"], env):
        t = ev.get("type", "")
        if t == "thread.started" and ev.get("thread_id"):
            db.run("UPDATE chats SET codex_session=? WHERE id=?", ev["thread_id"], chat_id)
        elif t == "item.completed":
            item = ev.get("item", {})
            kind = item.get("type") or item.get("item_type")
            if kind in ("agent_message", "assistant_message") and item.get("text"):
                db.add_message(chat_id, "assistant", item["text"], label)
            elif kind == "command_execution":
                db.add_message(chat_id, "tool", f"shell  {short(item.get('command'))}", label)
            elif kind == "file_change":
                db.add_message(chat_id, "tool", f"edit  {short(item.get('changes'))}", label)
            elif kind == "web_search":
                db.add_message(chat_id, "tool", f"web_search  {short(item.get('query'))}", label)
        elif t in ("error", "turn.failed"):
            ok = False
            msg = short(ev.get("message") or ev.get("error") or ev, 1500)
            limited = limited or bool(LIMIT_WORDS.search(msg))
            db.add_message(chat_id, "error", msg, label)
        elif t == "_exit" and ev["code"] != 0:
            ok = False
            if ev["stderr"]:
                db.add_message(chat_id, "error", short(ev["stderr"], 1500), label)
    return ok, limited
