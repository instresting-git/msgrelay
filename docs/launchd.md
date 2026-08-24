# macOS 排程（launchd）

MsgRelay 在 macOS 上建議用 launchd 代替 cron（macOS 對 cron 支持不佳）。

## 1. 同步任務（每 10 分鐘）

`~/Library/LaunchAgents/com.msgrelay.sync.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.msgrelay.sync</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-lc</string>
        <string>~/bin/wacli --account personal sync &amp;&amp; ~/bin/wacli --account work sync</string>
    </array>
    <key>StartInterval</key>
    <integer>600</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/YOU/.wacli/logs/sync.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/YOU/.wacli/logs/sync.err</string>
</dict>
</plist>
```

> 把 `YOU` 換成你的用戶名。多帳號建議錯開：work 帳號加 `StartInterval` 300 秒偏移（即拆成兩個 plist，一個間隔 600 秒、一個間隔 600 秒但首次延遲 300 秒）。

## 2. 加載

```bash
launchctl load ~/Library/LaunchAgents/com.msgrelay.sync.plist
launchctl start com.msgrelay.sync   # 立即測試
```

## 3. 日曆/任務同步（每天 09:30）

`~/Library/LaunchAgents/com.msgrelay.pipeline.plist`：

```xml
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.msgrelay.pipeline</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-lc</string>
        <string>
            python3 ~/.wacli/scripts/wacli_calendar.py --once &amp;&amp;
            python3 ~/.wacli/scripts/wacli_tasks.py --once
        </string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>9</integer>
        <key>Minute</key><integer>30</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/YOU/.wacli/logs/pipeline.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/YOU/.wacli/logs/pipeline.err</string>
</dict>
</plist>
```

## 4. 日報（每天 18:00）+ 清理（每天 03:00）

同理創建 `com.msgrelay.reports.plist`（`StartCalendarInterval` 18:00，跑 `wacli_reports.py --mode daily`）和 `com.msgrelay.cleanup.plist`（03:00，跑 `bash ~/.wacli/scripts/cleanup.sh`）。

## 5. 常見問題

- **launchd 環境沒有 PATH**：腳本裡用絕對路徑（`~/bin/wacli`、`/usr/bin/python3`），或在 `ProgramArguments` 用 `bash -lc` 加載 shell 環境
- **日誌**：所有輸出寫到 `~/.wacli/logs/`，排查問題先看這裡
- **卸載**：`launchctl unload ~/Library/LaunchAgents/com.msgrelay.xxx.plist`
