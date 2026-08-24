# MsgRelay 詳細配置指南

> 這是完整配置文檔。快速上手看根目錄的 `README.md`。

---

## 架構

```
WhatsApp  ──(wacli sync)──▶  本地 SQLite (~/.wacli/accounts/*/wacli.db)
                                    │
                                    ▼
                          ┌─────────────────────┐
                          │  NLP 提取引擎         │  事件 / 任務 / deadline
                          │  (wacli_nlp_extract) │  + 置信度評分
                          └─────────────────────┘
                                    │
              ┌─────────────────────┼──────────────────────┐
              ▼                     ▼                      ▼
     Google Calendar        Google Tasks            飛書 (Lark)
     (wacli_calendar)       (wacli_tasks)           Calendar/Tasks/Bitable
              │                     │                      │
              └─────────────────────┴──────────────────────┘
                                    │
                                    ▼
                        日報 / 週報 → Discord
                        (wacli_reports + wacli_notify)
```

所有組件都是**獨立腳本**，可以單獨運行，也可以通過 cron / launchd 定時調度。

---

## 配置

所有用戶特定配置集中在兩個文件：

| 文件 | 內容 |
|---|---|
| `~/.wacli/config.yaml` | wacli 帳號列表（多帳號） |
| `~/.wacli/scripts/wacli_secrets.json` | 所有憑證（chmod 600） |

### config.yaml

```yaml
default_account: personal

accounts:
  personal:
    store: accounts/personal
  work:
    store: accounts/work
```

> 任意數量的帳號都支持，MsgRelay 自動讀取。

### wacli_secrets.json

```json
{
  "google_client_id": "…",
  "google_client_secret": "…",
  "smtp_user": "your@email.com",
  "smtp_password": "…",
  "report_to": "you@email.com",
  "discord_webhook_url": "https://discord.com/api/webhooks/…",
  "lark_user_id": "ou_…"
}
```

### 環境變量覆蓋（可選）

| 變量 | 作用 | 默認 |
|---|---|---|
| `MSGRELAY_HOME` | 數據目錄 | `~/.wacli` |
| `MSGRELAY_TZ` | 日曆事件時區 | `Asia/Hong_Kong` |
| `MSGRELAY_LARK_USER_ID` | 飛書用戶 ID | secrets 讀取 |

### LLM 增強配置（可選，默認關閉）

在 `wacli_secrets.json` 添加（或使用同名環境變量 `MSGRELAY_LLM_*`）：

```json
{
  "llm_api_key": "sk-...",
  "llm_base_url": "https://api.deepseek.com/v1",
  "llm_model": "deepseek-chat"
}
```

- 兼容任何 OpenAI Chat Completions API：OpenAI、DeepSeek、Ollama（`http://localhost:11434/v1`）、LM Studio 等
- 配置後，`wacli_calendar.py` / `wacli_tasks.py` 自動使用 LLM 提取，失敗時自動回退規則引擎
- 不配置 = 純規則引擎（零外部依賴）

### Auto-learn（學習引擎）

反饋存於 `<MSGRELAY_HOME>/scripts/msgrelay_learn.json`：

| 命令 | 作用 |
|---|---|
| `--feedback <id> --action confirmed [--type] [--title]` | 標記提取正確 → 進入 LLM 正例庫 |
| `--feedback <id> --action ignored [--type] [--title]` | 標記提取錯誤 → 進入反例庫 + 規則懲罰 |
| `--stats` | 查看學習統計 |
| `--reset` | 清空學習數據 |

---

## ⏰ 排程設置

### macOS（launchd）

見 [launchd.md](launchd.md)——包含 sync、pipeline、reports、cleanup 的完整 plist 模板。

### Linux（cron）

```cron
*/10 * * * * /path/to/wacli --account personal sync
*/10 * * * * /path/to/wacli --account work sync
0 3 * * *   bash ~/.wacli/scripts/cleanup.sh
30 9 * * *  python3 ~/.wacli/scripts/wacli_calendar.py --once
30 9 * * *  python3 ~/.wacli/scripts/wacli_tasks.py --once
0 18 * * *  python3 ~/.wacli/scripts/wacli_reports.py --mode daily
```

---

## 隱私與安全

- **Local-first**：所有 WhatsApp 數據只存在你自己的機器上，MsgRelay 不收集、不上傳任何數據
- **憑證保護**：所有密鑰存於 `wacli_secrets.json`（chmod 600），從不硬編碼
- **去重機制**：消息處理有 checkpoint，日曆/任務有存在性檢查，不會重複創建
- **自動清理**：默認保留 14 天歷史，減少敏感數據留存

詳細見 [PRIVACY.md](PRIVACY.md)。

---

## 常見問題

**Q: 我會被封號嗎？**
MsgRelay 使用 WhatsApp Web 非官方協議（whatsmeow），理論上存在帳號受限風險。建議使用次要號碼或接受風險。詳細見 [DISCLAIMER.md](DISCLAIMER.md)。

**Q: 支持多少個 WhatsApp 帳號？**
任意數量。在 config.yaml 中加帳號即可。

**Q: NLP 支持哪些語言？**
簡體中文、繁體中文（含粵語口語）、英文。混合語境也能處理。

**Q: 誤報怎麼辦？**
所有提取都附置信度評分，日曆/任務同步的門檻是 0.65（`wacli_calendar.py` / `wacli_tasks.py` 中可調）。低置信度消息不會進入你的日曆。

**Q: 我的數據會上傳到哪裡？**
哪裡都不去。所有數據存儲在你自己機器上的 SQLite，MsgRelay 沒有任何雲端服務器。
