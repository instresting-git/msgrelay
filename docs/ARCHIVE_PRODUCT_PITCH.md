# MsgRelay — 產品銷售頁文案

> 一次性源碼買斷 · 無訂閱 · 無後續費用 · 數據 100% 本地

---

## 標題選項

**主標題**
> 你的 WhatsApp，變成你的項目管理系統

**副標題**
> MsgRelay 自動從聊天中提取會議、任務和截止日期，同步到 Google Calendar / Tasks / 飛書——獨立開發者的消息不再「看過就丟」。

---

## 痛點（你的客戶在哪裡）

- 客戶 / 協作者習慣用 WhatsApp 溝通，項目信息散落在聊天記錄裡
- 會議時間、deadline、待辦事項在聊天裡「說過就忘」
- 手動把消息抄進日曆 / 任務清單 = 每天 30–60 分鐘重複勞動
- 用 Notion / Linear / 飛書，但消息進來還是在 WhatsApp

## 解決方案

MsgRelay 監聽你的 WhatsApp 消息，用三語 NLP 引擎自動識別：

- 📅 「聽日下晝 3 點開會傾 project 進度」→ Google Calendar 事件（帶提醒）
- ✅ 「記得跟進個 client 個 case」→ Google Tasks 任務
- ⏰ 「下星期三 deadline 前要交 report」→ 帶截止日期的任務
- 📊 每天 18:00 自動生成日報：今天聊了什麼、跟誰、多少條、關鍵內容摘要

## 賣點

1. **中英粵三語** —— 香港/內地/國際客戶的混合語境，開箱即用
2. **置信度評分** —— 低置信度消息不會誤入你的日曆（0.65 門檻可調）
3. **Local-first** —— 數據永不離開你的機器，沒有雲端隱私風險
4. **多帳號** —— Work / Personal 任意數量帳號
5. **去重保護** —— 同一個事件絕不會在你的日曆出現兩次
6. **源碼買斷** —— 你擁有代碼，可以改，可以商用，無訂閱

## 包含內容

- ✅ 完整 Python 源碼（NLP 引擎 + Google Calendar/Tasks + 日報週報 + 通知）
- ✅ 飛書集成模塊（Calendar / Tasks / Bitable）
- ✅ 一鍵安裝腳本（`bash setup.sh`）
- ✅ 完整文檔（README + launchd/cron 排程指南）
- ✅ 源碼買斷許可證（可個人/商業使用，禁止再分發）

## 定價建議

| 版本 | 內容 | 價格 |
|---|---|---|
| **Standard** | Google 集成 + NLP + 報告 | **$79 USD** |
| **Pro**（推薦） | Standard + 飛書模塊 | **$129 USD** |

*一次性買斷，含 1 年內的小版本更新（如適用）。不含定制開發與技術支持。*

## 常見問題

**Q: 我會被封號嗎？**
A: MsgRelay 使用 WhatsApp Web 非官方協議（whatsmeow），理論上存在帳號受限風險。建議使用次要號碼或接受風險。這是所有同類工具（whatsapp-web.js 等）的共同限制。

**Q: 我的數據會上傳到哪裡？**
A: 哪裡都不去。所有數據存儲在你自己機器上的 SQLite，MsgRelay 沒有任何雲端服務器。

**Q: 賣了之後有更新嗎？**
A: 源碼買斷模式：你拿到的是當前版本的完整源碼。如需定制（新集成、新語言），可另行聯繫。

**Q: 我是 Mac 還是 Linux 用戶？**
A: 都支持（macOS arm64/amd64、Linux arm64/amd64）。

---

## 銷售渠道建議

1. **Lemon Squeezy**（推薦）— 自動處理全球稅務（VAT/GST），支持源碼交付，買家體驗好
2. **Gumroad** — 簡單快速，社區大，適合冷啟動
3. **X / Twitter + Indie Hackers** — 發布 launch thread，target #buildinpublic 社群
4. **Product Hunt** — 有完整 README + demo GIF 後可以衝一波

## 發布 Checklist

- [ ] 錄一個 60–90 秒 demo 視頻（配對 → 發消息 → 日曆出現事件 → 日報）
- [ ] 準備 3 張截圖（NLP 測試輸出 / 日曆事件 / 日報 Discord）
- [ ] 定價頁 + FAQ
- [ ] 隱私頁（一句話：數據 100% 本地）
- [ ] 在 Reddit r/selfhosted、r/WhatsApp 做 soft-launch 帖
