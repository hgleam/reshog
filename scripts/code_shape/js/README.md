# code_shape/js

TypeScript / JavaScript の形を、構文木なしで測る側（`code_shape/scan.py` が `js/shape.py` の
`measure_js` を呼ぶ）。 親の `code_shape/README.md` と同じく、写した先では直さない（直すのは
`code_shape/constants.py` だけ）。

## 置くもの / 置かないもの

- 置く: TypeScript / JavaScript の字句処理・関数の形の測り・無名関数の名前の推定
- 置かない: 対象の収集・台帳（`code_shape/scan.py`・`code_shape/ledger.py`）、JSX
  の行の数え（`code_shape/jsx_lines.py`）

## ディレクトリ構成

```
.
├── README.md    # この文書
├── __init__.py  # このディレクトリを Python のパッケージにする
├── shape.py     # 関数・クラスの形を測る
├── names.py     # 無名の関数に、置かれた場所から名前を推す
└── text.py      # コメント・文字列を消し、括弧の対応を取る
```
