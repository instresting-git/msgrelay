# ChatFlow — WhatsApp → Automation Workflows

> 把 WhatsApp 消息變成你的項目管理系統。自動提取會議、任務、截止日期，同步到 Google Calendar / Tasks / 飛書，每天自動生成工作報告。

**中 / 英 / 粵三語 NLP** · **Local-first（數據永不離開你的機器）** · **MIT 開源**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-green.svg)]()
[![Tests](https://img.shields.io/badge/tests-20%2F20%20passing-brightgreen.svg)](tests/)

ChatFlow 是給**獨立開發者 / Freelancer / 小團隊**的 WhatsApp 自動化集成層。它把散落在 WhatsApp 聊天裡的項目信息（會議時間、待辦事項、deadline、跟進事項）自動提取出來，變成結構化的日曆事件、任務清單和每日/每週報告。

**數據永遠留在你自己的機器上**，不經過任何第三方服務器。

---

## ✨ 功能一覽

| 模塊 | 功能 |
|---|---|
| 🧠 **NLP 提取引擎** | 中 / 英 / 粵三語事件、任務、deadline 自動識別，附置信度評分 |
| 📅 **Google Calendar 同步** | 自動創建日曆事件（含提醒），智能去重 |
| ✅ **Google Tasks 同步** | 自動創建任務（含截止日期），智能去重 |
| 📊 **日報 / 週報** | 每日/每週消息統計 + 關鍵內容摘要，推送到 Discord |
| 🔔 **統一通知** | 標準化 Discord 推送（5 分鐘去重窗口，防重複發送） |
| 💼 **多帳號支持** | 任意數量的 WhatsApp 帳號，從 config.yaml 動態讀取 |
| 🧹 **自動清理** | 保留 14 天消息歷史，自動清理（可配置） |
| 🌐 **飛書集成** | Lark Calendar / Tasks / Bitable 同步（OAuth 全流程） |

## 🚀 快速開始

```bash
# 1. 克隆
git clone https://github.com/KelvinOr/chatflow.git && cd chatflow

# 2. 一鍵安裝（下載 wacli + 安裝腳本 + 生成配置模板）
bash scripts/setup.sh

# 3. 配對 WhatsApp（掃 QR 碼）
wacli --account personal pair

# 4. 填寫憑證 ~/.wacli/scripts/wacli_secrets.json
# 5. Google OAuth（一次性）
python3 ~/.wacli/scripts/wacli_calendar.py --auth
python3 ~/.wacli/scripts/wacli_tasks.py --auth

# 6. 測試管道
python3 ~/.wacli/scripts/wacli_calendar.py --once
python3 ~/.wacli/scripts/wacli_reports.py --mode daily
```

完整指南見 [README 詳細版](docs/README_FULL.md) 和 [macOS 排程指南](docs/launchd.md)。

## 🧠 NLP 引擎示例

```bash
python3 src/wacli_nlp_extract.py
```

```
[event/meeting] (95%) 聽日下晝3點開會傾project進度   → 2026-08-25 15:00
[task/deadline] (90%) 下星期三deadline前要交report   → due 2026-09-02
[event/meeting] (95%) tomorrow 2pm meeting with team → 2026-08-25 14:00
[task]          (90%) 記得跟進個client個case
```

## 🧪 測試

20 個測試覆蓋 NLP 多語言、多帳號配置、DB 層、端到端集成、報告構建。可在 Docker 或本地運行：

```bash
docker build -t chatflow-test . && docker run --rm chatflow-test
# 或本地
python -m unittest discover -s tests -v
```

## 🤝 貢獻與需求

這個項目用 **GitHub Issues / Discussions 收集需求**——你的使用場景就是產品的路線圖：

- 🐛 遇到 bug？[開 issue](https://github.com/KelvinOr/chatflow/issues/new)
- 💡 想要新語言 / 新集成（Notion? Slack?）？[開 discussion](https://github.com/KelvinOr/chatflow/discussions)
- 📝 想改進代碼？看 [CONTRIBUTING.md](CONTRIBUTING.md)

## ☕ 支持

如果你覺得 ChatFlow 有用，可以：

- ⭐ 給 repo 一個 star（免費但很有用）
- ☕ [在 GitHub Sponsors 上支持我](https://github.com/sponsors/KelvinOr)——開發者維護全靠愛發電，你的支持直接決定新功能的速度

## ⚠️ 免責聲明

- ChatFlow 是**第三方工具**，使用 WhatsApp Web 協議（whatsmeow），**與 WhatsApp / Meta 無關**
- 使用非官方協議**可能違反 WhatsApp 服務條款**，存在帳號受限風險——請自行承擔
- 詳細聲明見 [DISCLAIMER.md](docs/DISCLAIMER.md)

## 📄 許可

- ChatFlow：**MIT License**（見 [LICENSE](LICENSE)）
- wacli：MIT License · whatsmeow：MPL-2.0（見 LICENSE 中的第三方聲明）

---

*Made by a SOC engineer who got tired of losing project info in WhatsApp chats.*
