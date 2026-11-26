# .githooks

コミットされる git フックの本体。`.git/hooks` はコミットできないので、本体をここに置き、clone ごとに繋ぐ。

- **置くもの**: 追跡するフック（`pre-commit`）。main への直接コミットの拒否・仕様鮮度の門・全テストの実行
- **置かないもの**: commit-msg ガード（`install-commit-msg-guard.sh` が git 管理外の `.git/hooks` へ置く）

## ディレクトリ構成

```
.githooks/
├── README.md   # この文書
└── pre-commit  # main への直接コミットの拒否・仕様鮮度・全テスト
```
