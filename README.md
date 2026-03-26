# Sentiment Scout 🔭

輿情監控 + 論點草稿產生器

監控社群平台上特定事件的討論風向，分析情緒分佈與主要論點，並根據你設定的立場產生回覆草稿。**所有發文動作由使用者手動執行。**

## 架構

```
sentiment-scout/
├── config/
│   ├── settings.yaml          # 全域設定（API keys、監控關鍵字、立場設定）
│   └── stances.yaml           # 立場定義檔
├── src/
│   ├── collectors/            # 資料收集模組（各平台爬取）
│   │   ├── base.py
│   │   ├── reddit.py          # ✅ Phase 1
│   │   ├── ptt.py             # Phase 2
│   │   ├── twitter.py         # Phase 3
│   │   └── threads.py         # Phase 4
│   ├── analyzers/             # 分析模組
│   │   ├── sentiment.py       # 情緒分析
│   │   └── topic.py           # 主題/論點歸納
│   ├── drafter/               # 草稿產生器
│   │   └── reply_drafter.py   # 根據立場產生回覆草稿
│   ├── storage/               # 資料儲存
│   │   └── db.py              # SQLite 儲存討論與分析結果
│   └── dashboard/             # 本機儀表板
│       └── app.py             # Streamlit 儀表板
├── tests/
├── requirements.txt
├── .env.example
└── README.md
```

## 開發順序

| Phase | 平台    | 說明                          |
| ----- | ------- | ----------------------------- |
| 1     | Reddit  | PRAW，API 最友善              |
| 2     | PTT     | 爬蟲 / PTT Web API           |
| 3     | Twitter | 需 API key，有 rate limit     |
| 4     | Threads | Meta API，較新較受限          |

## 快速開始

```bash
# 1. 建立虛擬環境
python3 -m venv venv
source venv/bin/activate

# 2. 安裝依賴
pip install -r requirements.txt

# 3. 設定環境變數
cp .env.example .env
# 編輯 .env 填入你的 Reddit API credentials

# 4. 設定監控目標與立場
# 編輯 config/settings.yaml

# 5. 執行收集
python -m src.collectors.reddit

# 6. 啟動儀表板
streamlit run src/dashboard/app.py
```

## Reddit API 設定

1. 到 https://www.reddit.com/prefs/apps 建立 app
2. 選 "script" 類型
3. 拿到 client_id 和 client_secret
4. 填入 .env

## 倫理聲明

本工具僅供輿情監控與論點參考，不包含任何自動發文功能。使用者應自行判斷是否、如何參與討論，並遵守各平台的使用條款。
