# ドキュメント目次

## ディレクトリ構成

```
docs/
├── README.md       # この目次
├── devlog.md       # 取り組みログ（過程・当初案→変更→理由）
├── decisions/      # 決定記録 ADR（構成は decisions/README.md）
├── design-notes/   # 未確定の論点（構成は design-notes/README.md）
├── metrics/        # 計測の台帳（構成は metrics/README.md）
├── playbooks/      # 手順・理由・事例・表の置き場（構成は playbooks/README.md）
└── specification/  # 仕様書（構成は specification/README.md）
```

## 領域の使い分け

| 領域 | 何を書くか | いつ更新するか | 入口 |
|------|-----------|---------------|------|
| 仕様書 `specification/` | 結果＝いま何がどうなっているか | 仕様変更と同コミット（freshness 強制） | [specification/README.md](specification/README.md) |
| 取り組みログ `devlog.md` | 過程＝壁打ちのブラッシュアップ（当初案→変更→理由） | 作業アーク完了時 | [devlog.md](devlog.md) |
| 決定記録 `decisions/` | 深掘りが要る決定（ADR） | 重い意思決定の確定時 | [decisions/README.md](decisions/README.md) |
| 設計メモ `design-notes/` | 未確定の論点 | 論点発生時／確定で仕様書へ移す | [design-notes/README.md](design-notes/README.md) |
| 計測の台帳 `metrics/` | 複雑度の計測結果とコードの形の台帳 | 大きな変更・リファクタの後／予算超えを直したとき。絶対値でなく前回からの向きを見る | [metrics/README.md](metrics/README.md) |
| 手順書 `playbooks/` | 手順・理由・事例・表（`CLAUDE.md`・rules から 1 行で指す） | 予算検査が落ちたとき／規則に手順を書きたくなったとき | [playbooks/README.md](playbooks/README.md) |
