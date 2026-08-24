"""
Mock environment for MsgRelay tests.

Creates a realistic ~/.wacli layout in the container (or local machine):
  ~/.wacli/config.yaml
  ~/.wacli/accounts/{personal,work}/wacli.db   (mock WhatsApp message DB)
  ~/.wacli/scripts/wacli_secrets.json          (dummy credentials)

Must run BEFORE importing any MsgRelay module so module-level config resolves.
"""
import os
import json
import sqlite3
from datetime import datetime

WACLI_HOME = os.path.expanduser("~/.msgrelay-test")
SCRIPTS_DIR = os.path.join(WACLI_HOME, "scripts")

CONFIG_YAML = """# wacli multi-account configuration
default_account: personal

accounts:
  personal:
    store: accounts/personal
  work:
    store: accounts/work
"""

SECRETS = {
    "google_client_id": "test-client-id.apps.googleusercontent.com",
    "google_client_secret": "test-secret",
    "smtp_user": "test@example.com",
    "smtp_password": "test-password",
    "report_to": "test@example.com",
    "discord_webhook_url": "https://discord.com/api/webhooks/test/test",
    "lark_user_id": "ou_test123",
}

# (chat_jid, chat_name, sender_jid, sender_name, msg_id, ts_offset, from_me,
#  media_type, display_text, text)
SAMPLE_MESSAGES = [
    # Cantonese meeting with date + time
    ("123@s.whatsapp.net", "客戶群組", "456@s.whatsapp.net", "客戶A", "m1001", -3600, 0,
     "", "聽日下晝3點開會傾project進度", "聽日下晝3點開會傾project進度"),
    # Simplified Chinese deadline
    ("123@s.whatsapp.net", "客戶群組", "456@s.whatsapp.net", "客戶A", "m1002", -1800, 0,
     "", "下星期三deadline前要交report", "下星期三deadline前要交report"),
    # English meeting with bare am/pm time
    ("789@s.whatsapp.net", "Team", "790@s.whatsapp.net", "Boss", "m1003", -900, 0,
     "", "tomorrow 2pm meeting with team", "tomorrow 2pm meeting with team"),
    # Cantonese task
    ("789@s.whatsapp.net", "Team", "791@s.whatsapp.net", "Colleague", "m1004", -600, 0,
     "", "記得跟進個client個case", "記得跟進個client個case"),
    # English task with due
    ("789@s.whatsapp.net", "Team", "790@s.whatsapp.net", "Boss", "m1005", -500, 0,
     "", "Friday 4pm deadline for the proposal", "Friday 4pm deadline for the proposal"),
    # Casual chit-chat → should extract NOTHING
    ("111@s.whatsapp.net", "Family", "112@s.whatsapp.net", "Mum", "m1006", -300, 0,
     "", "今日天氣好好", "今日天氣好好"),
    # Deleted message → must be skipped by get_new_messages
    ("111@s.whatsapp.net", "Family", "112@s.whatsapp.net", "Mum", "m1007", -200, 0,
     "", "聽日開會", "聽日開會"),
    # Empty/placeholder text → skipped
    ("111@s.whatsapp.net", "Family", "113@s.whatsapp.net", "Dad", "m1008", -100, 0,
     "image", "(message)", "(message)"),
]

DELETED_TS = int(datetime.now().timestamp()) - 200  # marks m1007 deleted


def _create_db(path: str, messages: list):
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            chat_jid TEXT, chat_name TEXT, sender_jid TEXT, sender_name TEXT,
            msg_id TEXT PRIMARY KEY, ts INTEGER, from_me INTEGER,
            media_type TEXT, display_text TEXT, text TEXT, deleted_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chats (jid TEXT PRIMARY KEY, name TEXT)
    """)
    now = int(datetime.now().timestamp())
    for chat_jid, chat_name, sender_jid, sender_name, msg_id, ts_off, from_me, \
            media_type, display_text, text in messages:
        deleted_at = DELETED_TS if msg_id == "m1007" else None
        conn.execute(
            "INSERT OR REPLACE INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (chat_jid, chat_name, sender_jid, sender_name, msg_id,
             now + ts_off, from_me, media_type, display_text, text, deleted_at))
    conn.execute("INSERT OR REPLACE INTO chats VALUES (?,?)", ("123@s.whatsapp.net", "客戶群組"))
    conn.execute("INSERT OR REPLACE INTO chats VALUES (?,?)", ("789@s.whatsapp.net", "Team"))
    conn.execute("INSERT OR REPLACE INTO chats VALUES (?,?)", ("111@s.whatsapp.net", "Family"))
    conn.commit()
    conn.close()


def setup_mock_env():
    """Idempotent: create the whole mock ~/.wacli layout."""
    for d in ("accounts/personal", "accounts/work", "scripts"):
        os.makedirs(os.path.join(WACLI_HOME, d), exist_ok=True)

    cfg = os.path.join(WACLI_HOME, "config.yaml")
    if not os.path.exists(cfg):
        with open(cfg, "w") as f:
            f.write(CONFIG_YAML)

    sec = os.path.join(SCRIPTS_DIR, "wacli_secrets.json")
    if not os.path.exists(sec):
        with open(sec, "w") as f:
            json.dump(SECRETS, f, indent=2)

    _create_db(os.path.join(WACLI_HOME, "accounts/personal/wacli.db"), SAMPLE_MESSAGES)
    _create_db(os.path.join(WACLI_HOME, "accounts/work/wacli.db"), [])

    # Point MSGRELAY_HOME at the isolated test dir — never touch real ~/.wacli
    os.environ["MSGRELAY_HOME"] = WACLI_HOME
    return WACLI_HOME


if __name__ == "__main__":
    print(f"Mock env created at {setup_mock_env()}")
