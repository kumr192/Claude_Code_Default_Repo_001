"""Orbit API server. Run on the VM:  uv run orbit-server"""

import asyncio
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from croniter import croniter
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, runners

CFG = config.load()
PORT = int(os.environ.get("ORBIT_PORT", "8787"))
LOCAL_URL = f"http://127.0.0.1:{PORT}"  # the hook calls back on this address
STATIC = Path(__file__).with_name("static")
TASKS: set[asyncio.Task] = set()  # keep references so turns are not garbage-collected


def auth(authorization: str = Header(default="")) -> None:
    if not secrets.compare_digest(authorization, f"Bearer {CFG['token']}"):
        raise HTTPException(401, "Bad or missing token")


def start_turn(chat_id: int, text: str, model: str) -> None:
    task = asyncio.create_task(runners.run_turn(chat_id, text, model, CFG, LOCAL_URL))
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)


# ---------- routines (scheduled tasks) ----------

async def scheduler() -> None:
    while True:
        now = time.time()
        for r in db.q("SELECT * FROM routines WHERE enabled=1"):
            base = r["last_run"] or r["created"]
            try:
                due = croniter(r["cron"], base).get_next(float)
            except Exception:
                continue
            if due <= now:
                db.run("UPDATE routines SET last_run=? WHERE id=?", now, r["id"])
                run_routine(r)
        await asyncio.sleep(20)


def run_routine(r: dict) -> int:
    title = f"⏱ {r['name']} · {time.strftime('%b %d %H:%M')}"
    chat_id = db.run(
        "INSERT INTO chats (title, model, routine_id, created) VALUES (?,?,?,?)",
        title, r["model"], r["id"], time.time(),
    )
    db.add_message(chat_id, "user", r["prompt"])
    start_turn(chat_id, r["prompt"], r["model"])
    return chat_id


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    task = asyncio.create_task(scheduler())
    yield
    task.cancel()


app = FastAPI(title="Orbit", lifespan=lifespan)


# ---------- UI ----------

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ---------- API ----------

class NewChat(BaseModel):
    title: str = "New chat"
    model: str = "auto"


class NewMessage(BaseModel):
    text: str
    model: str | None = None


class RoutineIn(BaseModel):
    name: str
    cron: str
    prompt: str
    model: str = "auto"
    enabled: bool = True


class Decision(BaseModel):
    approve: bool


class HookCheck(BaseModel):
    chat_id: int
    tool: str
    input: dict


@app.get("/api/config", dependencies=[Depends(auth)])
def get_config():
    return {"models": CFG["models"], "computer_url": CFG["computer_url"]}


@app.put("/api/models", dependencies=[Depends(auth)])
def set_models(models: list[str]):
    CFG["models"] = [m.strip() for m in models if m.strip()]
    config.save(CFG)
    return {"models": CFG["models"]}


@app.get("/api/chats", dependencies=[Depends(auth)])
def list_chats():
    return db.q("SELECT id, title, model, running, routine_id, created FROM chats ORDER BY id DESC LIMIT 200")


@app.post("/api/chats", dependencies=[Depends(auth)])
def create_chat(body: NewChat):
    cid = db.run("INSERT INTO chats (title, model, created) VALUES (?,?,?)", body.title, body.model, time.time())
    return db.one("SELECT * FROM chats WHERE id=?", cid)


@app.delete("/api/chats/{chat_id}", dependencies=[Depends(auth)])
def delete_chat(chat_id: int):
    db.run("DELETE FROM messages WHERE chat_id=?", chat_id)
    db.run("DELETE FROM chats WHERE id=?", chat_id)
    return {"ok": True}


@app.get("/api/chats/{chat_id}/messages", dependencies=[Depends(auth)])
def get_messages(chat_id: int, after: int = 0):
    chat = db.one("SELECT id, title, model, running FROM chats WHERE id=?", chat_id)
    if not chat:
        raise HTTPException(404, "No such chat")
    msgs = db.q("SELECT * FROM messages WHERE chat_id=? AND id>? ORDER BY id", chat_id, after)
    return {"chat": chat, "messages": msgs}


@app.post("/api/chats/{chat_id}/messages", dependencies=[Depends(auth)])
async def send_message(chat_id: int, body: NewMessage):
    chat = db.one("SELECT * FROM chats WHERE id=?", chat_id)
    if not chat:
        raise HTTPException(404, "No such chat")
    if chat["running"]:
        raise HTTPException(409, "This chat is still working. Wait for it to finish.")
    model = body.model or chat["model"]
    if chat["title"] == "New chat":
        db.run("UPDATE chats SET title=? WHERE id=?", body.text.strip().splitlines()[0][:60], chat_id)
    db.run("UPDATE chats SET model=? WHERE id=?", model, chat_id)
    db.add_message(chat_id, "user", body.text)
    start_turn(chat_id, body.text, model)
    return {"ok": True}


# ----- approvals -----

@app.post("/api/hook/check", dependencies=[Depends(auth)])
def hook_check(body: HookCheck):
    risky, detail = is_risky(body.tool, body.input)
    if not risky:
        return {"decision": "allow"}
    aid = db.run(
        "INSERT INTO approvals (chat_id, tool, detail, created) VALUES (?,?,?,?)",
        body.chat_id, body.tool, detail, time.time(),
    )
    db.add_message(body.chat_id, "system", f"Waiting for your approval: {body.tool} — {detail}")
    return {"decision": "ask", "approval_id": aid, "timeout": CFG["approval_timeout"]}


def is_risky(tool: str, data: dict) -> tuple[bool, str]:
    if tool == "Bash":
        cmd = str(data.get("command", ""))
        return bool(re.search(CFG["risky_bash"], cmd, re.I)), cmd[:500]
    if tool.startswith("mcp__playwright__") and any(k in tool for k in ("click", "type", "press", "select", "fill")):
        label = " ".join(str(data.get(k, "")) for k in ("element", "text", "key", "values"))
        return bool(re.search(CFG["risky_browser"], label, re.I)), f"{tool.split('__')[-1]}: {label[:300]}"
    return False, ""


@app.get("/api/approvals", dependencies=[Depends(auth)])
def list_approvals(status: str = "pending"):
    return db.q(
        "SELECT a.*, c.title AS chat_title FROM approvals a LEFT JOIN chats c ON c.id=a.chat_id "
        "WHERE a.status=? ORDER BY a.id DESC LIMIT 100", status,
    )


@app.get("/api/approvals/{aid}", dependencies=[Depends(auth)])
def get_approval(aid: int):
    a = db.one("SELECT * FROM approvals WHERE id=?", aid)
    if not a:
        raise HTTPException(404, "No such approval")
    # Expire old requests so the hook does not wait forever.
    if a["status"] == "pending" and time.time() - a["created"] > CFG["approval_timeout"]:
        db.run("UPDATE approvals SET status='denied' WHERE id=?", aid)
        a["status"] = "denied"
    return a


@app.post("/api/approvals/{aid}", dependencies=[Depends(auth)])
def decide_approval(aid: int, body: Decision):
    a = db.one("SELECT * FROM approvals WHERE id=?", aid)
    if not a:
        raise HTTPException(404, "No such approval")
    status = "approved" if body.approve else "denied"
    db.run("UPDATE approvals SET status=? WHERE id=? AND status='pending'", status, aid)
    db.add_message(a["chat_id"], "system", f"You {status}: {a['tool']}")
    return {"status": status}


# ----- routines -----

@app.get("/api/routines", dependencies=[Depends(auth)])
def list_routines():
    rows = db.q("SELECT * FROM routines ORDER BY id DESC")
    for r in rows:
        try:
            r["next_run"] = croniter(r["cron"], time.time()).get_next(float) if r["enabled"] else None
        except Exception:
            r["next_run"] = None
    return rows


@app.post("/api/routines", dependencies=[Depends(auth)])
def create_routine(body: RoutineIn):
    if not croniter.is_valid(body.cron):
        raise HTTPException(400, "Bad schedule. Example: '0 9 * * 1-5' = weekdays at 09:00 (VM time, UTC).")
    rid = db.run(
        "INSERT INTO routines (name, cron, prompt, model, enabled, created) VALUES (?,?,?,?,?,?)",
        body.name, body.cron, body.prompt, body.model, int(body.enabled), time.time(),
    )
    return db.one("SELECT * FROM routines WHERE id=?", rid)


@app.put("/api/routines/{rid}", dependencies=[Depends(auth)])
def update_routine(rid: int, body: RoutineIn):
    if not croniter.is_valid(body.cron):
        raise HTTPException(400, "Bad schedule.")
    db.run(
        "UPDATE routines SET name=?, cron=?, prompt=?, model=?, enabled=? WHERE id=?",
        body.name, body.cron, body.prompt, body.model, int(body.enabled), rid,
    )
    return db.one("SELECT * FROM routines WHERE id=?", rid)


@app.delete("/api/routines/{rid}", dependencies=[Depends(auth)])
def delete_routine(rid: int):
    db.run("DELETE FROM routines WHERE id=?", rid)
    return {"ok": True}


@app.post("/api/routines/{rid}/run", dependencies=[Depends(auth)])
async def run_routine_now(rid: int):
    r = db.one("SELECT * FROM routines WHERE id=?", rid)
    if not r:
        raise HTTPException(404, "No such routine")
    return {"chat_id": run_routine(r)}


def cli() -> None:
    import uvicorn
    host = os.environ.get("ORBIT_HOST", "0.0.0.0")
    print(f"Orbit on http://{host}:{PORT}  token: {CFG['token']}")
    uvicorn.run(app, host=host, port=PORT)
