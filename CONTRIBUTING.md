# Contributing to MsgRelay

感謝你有興趣改進 MsgRelay！這個項目的路線圖完全由社區需求驅動。

## 🐛 報告 Bug

開 issue 時請包含：

1. 環境：OS（macOS/Linux）、Python 版本、wacli 版本（`wacli --version`）
2. 重現步驟（越具體越好）
3. 預期行為 vs 實際行為
4. 日誌輸出（`~/.wacli/logs/` 下的相關內容）

## 💡 功能建議

先開 **Discussion** 而不是直接開 issue——我們先討論需求是否值得做、怎麼做，避免重複勞動。

## 🔧 開發流程

```bash
# 1. Fork 並克隆
git clone https://github.com/instresting-git/msgrelay.git
cd msgrelay

# 2. 安裝依賴
pip install -r requirements.txt

# 3. 跑測試（確保全綠）
python -m unittest discover -s tests -v

# 4. 開發...
# 5. 提交前再跑一次測試，然後開 PR
```

## ✅ PR 規範

- 每個 PR 一個主題（不要混多個功能）
- 附測試：新功能必須有對應的 unittest（看 `tests/test_pipeline.py` 的模式）
- 保持向後兼容；破壞性變更請在 PR 描述中標明
- 不要包含任何個人配置/憑證（參考 `tests/mock_env.py` 的 mock 方式）

## 🧪 測試新增模式

```python
# tests/test_pipeline.py 中添加：
def test_your_new_feature(self):
    items = _analyze("你的測試消息")
    self.assertEqual(items[0]["type"], "event")
```

## 📝 代碼風格

- Python 3.10+，類型註釋（`Optional[tuple]` 風格）
- 保持「無第三方框架依賴」——目前只有 Google API 客戶端和 requests 是必要的
- 中文註釋歡迎，但代碼標識符用英文

## ⚠️ 注意

- 不要提交任何真實的 `wacli_secrets.json`、token 或個人數據
- 涉及 WhatsApp 協議層面的改動請先討論——那是 wacli 的領域，MsgRelay 只做數據處理
