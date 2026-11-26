# tests

pytest のテスト。機能のテスト（解析・集約・描画・CLI）と、リポジトリの構造を固定する検査（文書・層・コードの形・資格情報の混入）が入る。

- **置くもの**: `test_*.py`・共有の補助（`conftest.py`）。外部コマンドは `collect` をモックするので macOS 以外でも流れる
- **置かないもの**: テスト以外のコード（`scripts/`）。実機の出力をそのまま写した個人のデータ（合成した値を書く）
- 件数と対象の表は `docs/specification/develop/testing.md`

## ディレクトリ構成

```
tests/
├── README.md                       # この文書
├── conftest.py                     # 描画した表から列名でセルを取る補助
├── test_all_tests_wired.py         # 置いてあるだけで実行されないテストの検出
├── test_churn.py                   # 短命プロセスの寄せ方・表示名・表・JSON
├── test_claude_md_budget.py        # CLAUDE.md と rules の大きさの予算
├── test_claude_sessions.py         # --project の Claude Code のセッション
├── test_cli_smoke.py               # 実エントリを subprocess で叩く
├── test_cli_view.py                # 表示の振り分けと --watch
├── test_code_shape_ratchet.py      # コードの形の悪化した向きだけ落とす
├── test_control.py                 # プロセス停止の結果コード
├── test_cpu.py                     # CPU 表示
├── test_definitions_live_apart.py  # 実装のファイルに定数・型を置かない
├── test_directory_readmes.py       # README の無いディレクトリの検出
├── test_doc_dedup.py               # 文書間の散文の再掲
├── test_doc_facts.py               # 文書の数値とコード実値の照合
├── test_doc_test_counts.py         # テスト件数の表と実際の収集数の照合
├── test_doc_tree.py                # 構成ツリーと実ファイルの照合
├── test_group.py                   # アプリ名の決め方と集約
├── test_known_processes.py         # OS のプロセスの説明
├── test_launchd_stop.py            # launchd ジョブの止め方の案内
├── test_layer_side_effects.py      # 副作用を持てるファイルの固定
├── test_llama_sleep.py             # llama-server の休止状態
├── test_models.py                  # GPU 常駐の判定
├── test_no_secret_literals.py      # 資格情報・個人パスのリテラルの混入
├── test_origin.py                  # PJ 列（由来の判定）
├── test_parse.py                   # top・ps 等の出力の解析
├── test_project_totals.py          # --project の PJ 別の合計
├── test_render.py                  # 整形・escape・提案コマンド
├── test_report.py                  # 一覧・システム状況の組み立て
├── test_spec_freshness.py          # 仕様鮮度の仕組み
├── test_spec_no_history.py         # 仕様書への変更履歴の混入
├── test_src_layers.py              # パッケージの層と import の向き
├── test_started.py                 # 起動列
├── test_structure.py               # 置き場所の約束
└── test_trend.py                   # 短命プロセスの記録と増加
```
