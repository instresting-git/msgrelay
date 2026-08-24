# ChatFlow — 隱私政策（Privacy Policy）

生效日期：2026 年

**一句話總結：ChatFlow 不收集任何數據。所有 WhatsApp 數據 100% 存儲在您自己的設備上。**

---

## 1. 我們收集什麼

**我們（ChatFlow 開發者）不收集任何個人信息。** 具體而言：

- ❌ 不收集您的姓名、郵箱、電話號碼
- ❌ 不收集您的 WhatsApp 消息內容
- ❌ 不收集您的聊天記錄、聯繫人、群組信息
- ❌ 不收集使用統計、遙測數據或崩潰報告
- ❌ 無雲端服務器、無帳戶系統、無後台分析

本產品是**本地運行**的開源代碼集合，所有處理都在您自己的計算機上完成。

## 2. 您的數據存放在哪裡

| 數據 | 位置 |
|---|---|
| WhatsApp 消息（SQLite） | 您設備上的 `~/.wacli/accounts/*/wacli.db` |
| 處理狀態（去重 checkpoint） | `~/.wacli/scripts/wacli_processed.json` |
| Google OAuth Token | `~/.wacli/scripts/google_token*.json`（本地） |
| 報告存檔 | `~/.wacli/reports/` |
| 憑證（client secret 等） | `~/.wacli/scripts/wacli_secrets.json`（chmod 600） |

**這些文件從不離開您的設備。**

## 3. 第三方服務的數據流向

ChatFlow 的功能需要與您自己的第三方帳戶互動。**這些連接由您發起、以您的身份進行**：

- **Google Calendar / Tasks**：您授權後，本產品在您本機直接調用 Google API 創建事件/任務。Google 按 [Google 隱私政策](https://policies.google.com/privacy) 處理數據
- **飛書（Lark）**：同上，數據流向飛書，按飛書隱私政策處理
- **Discord**：日報/週報通過您提供的 webhook URL 發送到您指定的 Discord 頻道
- **WhatsApp / Meta**：本產品通過 wacli 在本機連接 WhatsApp Web 協議鏡像消息，**消息不經任何第三方服務器中轉**

## 4. 數據控制者與處理者

- **您**（用戶）是您個人數據的**控制者（Data Controller）**——您決定處理什麼、怎麼處理
- **ChatFlow 開發者**不是數據處理者：我們不訪問、不存儲、不處理您的任何數據
- 本產品僅在您的設備上執行您指示的本地操作

## 5. 法律合規（GDPR / 香港 PDPO）

- **GDPR**：本產品不涉及個人數據傳輸至歐盟境外——數據不離開您的設備。若您將數據同步至 Google/飛書等服務，適用該服務的隱私政策
- **香港《個人資料（私隱）條例》（PDPO）**：本產品不收集、不持有您的個人資料，不屬於資料使用者（Data User）範疇

## 6. 數據刪除

刪除即徹底刪除，無任何副本：

- 刪除 `~/.wacli/` 目錄即可移除所有本地數據
- 第三方服務中的數據（日曆事件、任務）請在相應服務中刪除

## 7. 政策變更

若本政策發生重大變更（例如未來引入遙測），我們會在本文件中更新並標註生效日期。

---

*隱私問題請直接聯繫我們。*
