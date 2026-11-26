# docs/metrics

計測の台帳。コードの形のラチェットの台帳と、複雑度監査の計測結果が入る。

- **置くもの**: `code-shape.json`（導入時の実測値。予算を超えている借金も、そのまま写してある。測る道具は `scripts/code_shape/`、合否は `tests/test_code_shape_ratchet.py`）・`complexity-YYYYMMDD.json`（複雑度監査の計測結果）
- **置かないもの**: 手で書く文書（`code-shape.json` は `python3 scripts/code_shape --update-baseline <直したファイル>` で、直した入れ物の行だけ書き直す）

## ディレクトリ構成

```
docs/metrics/
├── README.md                  # この文書
├── code-shape.json            # コードの形の台帳
└── complexity-20260929.json   # 複雑度監査の計測結果（2026-09-29）
```
