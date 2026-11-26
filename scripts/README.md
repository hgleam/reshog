# scripts

リポジトリの門と開発の補助。仕様鮮度・main の出自の検査・自動マージの切り替え・コードの形を測る道具が入る。

- **置くもの**: シェルの門（`check-*.sh`）・自動マージの切り替え・コードの形を測る道具（`code_shape/`）
- **置かないもの**: アプリ本体のコード（`src/reshog/`）・テスト（`tests/`）・文書（`docs/`）

## ディレクトリ構成

```
scripts/
├── README.md                # この文書
├── automerge.sh             # 自動マージの切り替え（on / off / status）
├── check-main-genesis.sh    # main の履歴の出自を検査する（CI とローカル）
├── check-spec-freshness.sh  # コードを変えたのに仕様書が未更新のコミットを止める
└── code_shape/              # コードの形を測る道具（中は code_shape/README.md）
```
