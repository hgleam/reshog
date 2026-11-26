# .github/workflows

GitHub Actions のワークフロー。PR をテストでゲートし、通ったら自動でマージし、マージ済みの枝を掃除する。

- **置くもの**: ワークフロー（`*.yml`）
- **置かないもの**: ワークフローから呼ぶスクリプト（`scripts/`）。運用の説明（`docs/specification/develop/testing.md`）

## ディレクトリ構成

```
.github/workflows/
├── README.md                    # この文書
├── auto-merge.yml               # PR を開いたら自動マージを予約する
├── ci.yml                       # テストのゲート（ジョブ名 test が main 保護の必須チェック）
└── cleanup-merged-branches.yml  # マージ済みのリモートの枝を毎日掃除する
```
