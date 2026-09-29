# ドキュメント目次

## ディレクトリ構成

```
docs/
├── README.md
├── design-notes/
├── metrics/
└── specification/
```

## 領域の使い分け

| 領域 | 何を書くか | いつ更新するか | 入口 |
|------|-----------|---------------|------|
| 仕様書 `specification/` | 結果＝いま何がどうなっているか | 仕様変更と同コミット（freshness 強制） | [specification/README.md](specification/README.md) |
| 計測の台帳 `metrics/` | 複雑度の計測結果（`complexity-YYYYMMDD.json`。code-complexity-audit スキルの `complexity_report.py --json`） | 大きな変更・リファクタの後。絶対値でなく前回からの向きを見る | 各 JSON（`files[]` / `functions[]` / `classes[]`） |
| 設計メモ `design-notes/` | 未確定の論点 | 論点発生時／確定で仕様書へ移す | [design-notes/README.md](design-notes/README.md) |

取り組みログ（`devlog.md`）・決定記録（`decisions/`）は必要が生じた時点で作る
（内容が無いファイルは作らない）。
