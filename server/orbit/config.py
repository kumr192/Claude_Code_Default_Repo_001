"""Settings for Orbit. Stored in ~/.orbit/config.json on the VM.

No API keys live here. Claude and Codex use the logins you make
yourself with `claude auth login` and `codex login --device-auth`.
"""

import json
import os
import secrets
from pathlib import Path

HOME = Path(os.environ.get("ORBIT_HOME", Path.home() / ".orbit"))
CONFIG_FILE = HOME / "config.json"

DEFAULTS = {
    # Bearer token the desktop app must send. Made at first start.
    "token": "",
    # Folder where the agents work and keep files.
    "workspace": str(Path.home() / "workspace"),
    # Shown in the model dropdown. "provider:model". Edit freely.
    # Claude accepts aliases (opus, sonnet, haiku) or full model names.
    # Codex "default" means: use whatever your ChatGPT plan defaults to.
    "models": [
        "auto",
        "claude:opus",
        "claude:sonnet",
        "claude:haiku",
        "codex:default",
    ],
    # Used by "auto": Claude first, Codex when Claude hits its limit.
    "auto_primary": "claude:opus",
    "auto_fallback": "codex:default",
    # Live view of the cloud computer (noVNC). Filled in by bootstrap.sh.
    "computer_url": "",
    # Seconds to wait for you to approve a risky step before it is denied.
    "approval_timeout": 900,
    # Bash commands that need your approval (Python regex, case-insensitive).
    "risky_bash": r"(^|[\s;&|(])(rm|rmdir|shred|mkfs|dd|shutdown|reboot|kill|pkill|git\s+push|sendmail|mail|crontab)\b|curl\b.*-X\s*(POST|PUT|PATCH|DELETE)",
    # Browser clicks/typing on elements whose label matches this need approval.
    "risky_browser": r"\b(send|submit|post|publish|pay|buy|purchase|order|checkout|delete|remove|confirm|transfer)\b",
}


def load() -> dict:
    HOME.mkdir(parents=True, exist_ok=True)
    data = {}
    if CONFIG_FILE.exists():
        data = json.loads(CONFIG_FILE.read_text())
    cfg = {**DEFAULTS, **data}
    if not cfg["token"]:
        cfg["token"] = secrets.token_hex(24)
        save(cfg)
    Path(cfg["workspace"]).mkdir(parents=True, exist_ok=True)
    return cfg


def save(cfg: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    CONFIG_FILE.chmod(0o600)
