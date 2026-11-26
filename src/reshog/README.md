# reshog（パッケージ）

macOS の実メモリ・CPU を食っているプロセスを特定して出す本体。`cli.py` が入口（`memhog` / `cpuhog`）で、残りは外部コマンドの読み取り・解析・集約・組み立て・描画の部品。

- **置くもの**: 実行時のコード。部品は 1 ファイル 1 役割で直下に平置きし、読んでよい向きは `tests/test_src_layers.py` の表で固定している
- **置かないもの**: テスト（`tests/`）・補助スクリプト（`scripts/`）・仕様（`docs/specification/`）。定数と型は実装に足さず、`constants.py` と `models.py` に置く

## ディレクトリ構成

```
src/reshog/
├── README.md     # この文書
├── __init__.py   # パッケージの入口（版の再エクスポート）
├── aggregate.py  # プロセスを名前で束ねて合計し順位を付ける
├── churn.py      # 短命プロセスを数え始めから動いていた起動元へ寄せる
├── claude.py     # Claude Code のセッションの見分けと状態ファイルの場所
├── cli.py        # typer の入口（memhog / cpuhog）
├── collect.py    # top・ps・lsof・launchctl 等の外部コマンドで状況を読む I/O 層
├── constants.py  # 定数（しきい値・コマンド名・説明文）の唯一の置き場
├── control.py    # プロセスを止める（os.kill）副作用
├── group.py      # プロセスをアプリ単位へ集約する
├── known.py      # 上位に出る macOS のプロセスに用途と止めてよいかを添える
├── llama.py      # llama-server の休止状態の判定
├── models.py     # ドメインモデル（型の置き場）
├── origin.py     # プロセスの由来（どのプロジェクトから動いているか）の判定
├── parse.py      # top・memory_pressure 等の出力の解析
├── render.py     # 表と JSON への整形
├── report.py     # 収集と解析を組み合わせて一覧・システム状況を組み立てる
└── trend.py      # 短命プロセスの記録（--record）と増加（--trend）
```
