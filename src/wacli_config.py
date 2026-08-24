#!/usr/bin/env python3
"""
Shared configuration for ChatFlow (WhatsApp → automation workflows).

Design principles:
- Works with any number of wacli accounts (read from ~/.wacli/config.yaml).
- All secrets live in wacli_secrets.json (chmod 600) — never commit, never hardcode.
- Every user-specific value (timezone, email, phone labels) is configurable.

Environment overrides (optional):
    CHATFLOW_HOME     — base dir for reports/processed state (default: ~/.wacli)
    CHATFLOW_TZ       — timezone for calendar events (default: Asia/Hong_Kong)
"""
import os
import json
import sys
import yaml

# ── Paths ─────────────────────────────────────────────────────────
BASE_DIR = os.environ.get("CHATFLOW_HOME", os.path.expanduser("~/.wacli"))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
PROCESSED_FILE = os.path.join(SCRIPTS_DIR, "wacli_processed.json")
TOKEN_FILE = os.path.join(SCRIPTS_DIR, "google_token.json")
SECRETS_FILE = os.path.join(SCRIPTS_DIR, "wacli_secrets.json")

# ── Timezone (configurable) ───────────────────────────────────────
TIMEZONE = os.environ.get("CHATFLOW_TZ", "Asia/Hong_Kong")

# ── Branding (used in calendar event prefix / report footers) ─────
PRODUCT_NAME = "ChatFlow"
EVENT_PREFIX = "[WA]"
REPORT_FOOTER = "ChatFlow · WhatsApp automation"

# ── Email config (non-sensitive defaults; override in secrets) ────
SMTP_HOST = "smtp-mail.outlook.com"
SMTP_PORT = 587
SMTP_USER = ""   # set via wacli_secrets.json -> smtp_user
REPORT_TO = ""   # set via wacli_secrets.json -> report_to

# ── Google OAuth scopes ───────────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
]


def _load_wacli_config() -> dict:
    """Read ~/.wacli/config.yaml (wacli multi-account config)."""
    cfg_path = os.path.join(BASE_DIR, "config.yaml")
    try:
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        print(f"  ⚠️  wacli config not found: {cfg_path}", file=sys.stderr)
        return {}
    return cfg


def get_accounts() -> list[dict]:
    """
    Return the list of accounts from wacli config.yaml.

    Each entry: {"name": "personal", "db": "~/.wacli/accounts/personal/wacli.db",
                 "label": "Personal"}
    """
    cfg = _load_wacli_config()
    accounts_cfg = cfg.get("accounts", {})
    if not accounts_cfg:
        # Fallback: single default account
        accounts_cfg = {"default": {"store": "accounts/default"}}

    accounts = []
    for name, acct in accounts_cfg.items():
        store = acct.get("store", f"accounts/{name}")
        db_path = os.path.join(BASE_DIR, store, "wacli.db")
        if not os.path.exists(db_path):
            continue
        accounts.append({
            "name": name,
            "db": db_path,
            "label": name.capitalize(),
        })
    return accounts


# Backwards-compatible aliases (first two accounts, if present)
_ACCTS = get_accounts()
WORK_DB = _ACCTS[0]["db"] if len(_ACCTS) > 0 else ""
PERSONAL_DB = _ACCTS[1]["db"] if len(_ACCTS) > 1 else ""


def _load_secrets() -> dict:
    """Load secrets from the protected JSON file."""
    if not os.path.exists(SECRETS_FILE):
        raise RuntimeError(
            f"Secrets file not found: {SECRETS_FILE}\n"
            "Create it with: touch ~/.wacli/scripts/wacli_secrets.json && chmod 600 ~/.wacli/scripts/wacli_secrets.json\n"
            'Then add: {"google_client_id":"...","google_client_secret":"...","smtp_password":"..."}'
        )
    with open(SECRETS_FILE) as f:
        return json.load(f)


def get_google_credentials() -> dict:
    """Build Google OAuth credentials dict from secrets file."""
    secrets = _load_secrets()
    client_id = secrets.get("google_client_id", "")
    client_secret = secrets.get("google_client_secret", "")
    if not client_id or not client_secret:
        raise RuntimeError(
            "Google OAuth credentials missing in wacli_secrets.json.\n"
            'Required keys: "google_client_id", "google_client_secret"'
        )
    return {
        "installed": {
            "client_id": client_id,
            "project_id": "chatflow-integration",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": client_secret,
            "redirect_uris": ["http://localhost:5678/rest/oauth2-credential/callback"],
        }
    }


def get_smtp_password() -> str:
    """Read SMTP password from secrets file."""
    return _load_secrets().get("smtp_password", "")


def get_email_config() -> dict:
    """Resolve email sender/recipient (secrets override defaults)."""
    secrets = _load_secrets()
    return {
        "smtp_user": secrets.get("smtp_user", SMTP_USER),
        "report_to": secrets.get("report_to", REPORT_TO),
        "smtp_password": secrets.get("smtp_password", ""),
    }


def load_processed():
    """Load already-processed message IDs."""
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE) as f:
            return json.load(f)
    return {"calendar_events": [], "tasks": []}


def save_processed(data):
    """Save processed message IDs."""
    os.makedirs(os.path.dirname(PROCESSED_FILE), exist_ok=True)
    with open(PROCESSED_FILE, "w") as f:
        json.dump(data, f, indent=2)
