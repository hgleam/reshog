# code_shape

コードの「形」を測り、台帳を書く道具（init スキルの雛形の写し）。

- 測るもの（ファイル・関数）: 実行行・関数の行数・複雑度・関数の本数
- 測るもの（テストのファイル）:
  実行行と、テストケースでない関数（検査ロジックの補助）の行数・複雑度。ケースと本数・粒度は測らない
- 測るもの（ディレクトリ）: 直下の本数・名前の頭が同じ兄弟ファイルの本数
- 台帳: `docs/metrics/code-shape.json`
- 合否: `tests/test_code_shape_ratchet.py` が決める（ここは測るだけ）

## 置くもの / 置かないもの

- 置く: 測る処理・台帳の書き直し・その定数
- 置かない: 合否の判定と予算（`tests/test_code_shape_ratchet.py`）
- 置かない: 台帳そのもの（`docs/metrics/`）

## ディレクトリ構成

```
.
├── README.md     # この文書
├── __init__.py   # 外へ見せる名前（measure・BASELINE など）
├── __main__.py   # コマンド（python3 scripts/code_shape [--update-baseline [パス…] | --add-missing-kinds]。各フラグの意味は __init__.py の説明）
├── constants.py  # 定数（写した先で直すのは TARGETS・TEST_TARGETS・SKIP だけ）
├── scan.py       # 対象を集め、ファイルごとの形を組み立てる
├── dir_shape.py  # ディレクトリの粒度を測る（パスだけを見る）
├── py_shape.py   # Python を測る
├── js/           # TypeScript / JavaScript を測る（中は js/README.md）
├── jsx_lines.py  # 行数を数える用に、JSX の説明 {/* … */} の括弧を消す
└── ledger.py     # 台帳のうち、名指しした入れ物の行だけを書き直す
```
