# テスト・CI

## テスト構成

`tests/` 配下、pytest。`collect`（外部コマンド I/O）をモックするため macOS 非依存で CI（Linux）でも動く。

件数は pytest 収集数（parametrize 展開後）。合計 185。文書整合のスクリプト型テスト
（`python3 tests/test_doc_*.py` でも走るもの）は pytest からは 1 件に見えるので 1 と数え、
中の検査項目は「対象」に書く。この表と合計は `test_doc_test_counts.py` が実際の収集数と照合する。

| ファイル | 件数 | 対象 |
|---------|------|------|
| `test_models.py` | 6 | `Process.hidden_gpu` の判定（境界値・GPU 常駐/非常駐） |
| `test_parse.py` | 23 | `parse_mem_to_mb` / `parse_top_processes` / `parse_phys_mem` / `parse_free_percentage` / `parse_ps_snapshot` |
| `test_report.py` | 16 | `build_processes` / `build_groups` / `build_app_processes` / 走査幅 / `build_system_memory`（collect をモック） |
| `test_group.py` | 17 | `app_label` / `group_label`（親子・器の素通り・循環）/ `group_processes`（合算・順位） |
| `test_render.py` | 16 | `format_mb`（MB→G/M 整形）/ 他プロセス由来文字列のマークアップ escape / 提案コマンドの shlex クォート / CPU 表示 / 提案コマンドが並び順に合うこと / `COMMAND_BY_SORT` が唯一の正本であること |
| `test_cpu.py` | 15 | CPU 表示: 2 サンプル目だけを解析する / システム CPU の見出し / top を 2 回サンプルする / アプリ別の CPU 合計 |
| `test_cli_smoke.py` | 20 | 実エントリ（`python -m reshog.cli`）を subprocess で叩く（`--help` / `--version` / 併用制約のエラー / `--sort` / `cpuhog` / entry point の宣言）。版非互換・パース崩れの検出 |
| `test_origin.py` | 23 | PJ 列: `parse_lsof_cwd` / `parse_launchctl_list` / `repo_root`（worktree・submodule）/ `resolve` の判定順 / 表示分を 1 回の lsof で引くこと / 表・JSON |
| `test_started.py` | 18 | 起動列: `parse_etime_seconds`（`[[dd-]hh:]mm:ss`）/ `parse_ps_etime` / 「いま − 経過」/ 表・JSON |
| `test_project_totals.py` | 15 | `--project`: PJ 別の合計と順位 / PJ 不明を順位に混ぜず別に合計 / 全プロセスを 1 回の lsof で引くこと / PJ 列と同じ表記（`origin.label`）/ `bucket_processes` を `--group` と共有 / 表・JSON |
| `conftest.py` | — | `cell(rendered, pid, column)`: 描画した表から列名でセルを取る（行のどこかの `-` に当たって素通りするのを防ぐ） |
| `test_collect.py` | 4 | `send_signal`（os.kill をモック・例外→結果コード翻訳）/ `current_pid` |
| `test_spec_freshness.py` | 7 | 仕様書鮮度チェックの仕組みが揃っていることの構造テスト |
| `test_doc_tree.py` | 1 | 構成ツリー ↔ 実ファイルの双方向照合（漏れ／幽霊）＋2箇所以外への複製検出 |
| `test_doc_facts.py` | 1 | 文書の数値 ↔ コード実値（`--count` 既定・`HIDDEN_GPU_MIN_MB` ・`HIDDEN_GPU_RSS_RATIO` ・`GROUP_SAMPLE_MIN` ・`_MAX_CMD`） |
| `test_doc_dedup.py` | 1 | 文書間の再掲（本文で 40 文字以上の同一行が2文書にあれば FAIL） |
| `test_spec_no_history.py` | 1 | 仕様書に変更履歴（日付付きの「変更」「追加」等）が混ざっていないこと |
| `test_doc_test_counts.py` | 1 | この表 ↔ pytest の実際の収集数（行の漏れ・幽霊・件数・合計） |

### ドキュメント整合のテスト

コードを直して**文書だけ古い**状態は、通常のテストが緑でも起こる。閾値を変えたのに
`memory-detection.md` の定数表が古いと「なぜこの警告が出た/出ないか」の説明が実装と食い違う。
**正本＝コード**として機械照合する。

- 構成ツリーは **README を持つディレクトリがそれぞれ自分の直下だけを描く**（上位は1行に畳んで委譲）。
  同じファイル名がツリーに現れるのは1箇所だけなので二重化しない。
- 標準ライブラリのみで動くので、CI では**依存 install より前**に `Doc integrity` として走る
  （install が失敗しても文書のズレは検出できる）。`pytest` でも収集される。
- 雛形は `~/claude-private/.claude/skills/init/templates/`。他プロジェクトへも同手順で入る。

実行:

```bash
poetry run pytest -q      # テスト
poetry run ruff check .   # lint
poetry run mypy src       # 型チェック
```

## CI（GitHub Actions）

- `.github/workflows/ci.yml`。PR / main への push で `test` ジョブが走る。
  順序は **genesis 監査 → doc 整合 → 依存 install → ruff → mypy → pytest**。
  前 2 つは標準ライブラリだけで動くので install より前に置く（install が失敗しても検出できる）。
- **genesis 監査**（`scripts/check-main-genesis.sh`）: main の履歴ルートが「初回 scaffold のみ・1 個」
  であることをサーバ側で常時検証する。ローカルの pre-commit フックは人手・別マシン・別ツール由来の
  直コミットを見られないため、太い初回コミット・複数ルート（unrelated histories の接ぎ木）を CI で落とす。
  この検査には全履歴が要るので `checkout` は `fetch-depth: 0`。
- main 保護 ruleset で `test` を必須チェックにしており、緑にならないとマージできない
  （`pull_request` / `non_fast_forward` / `required_status_checks` の 3 ルール）。
- **auto-merge**（`.github/workflows/auto-merge.yml`）: PR が開かれると `gh pr merge --auto --squash`
  を予約する。`types` に `edited` / `synchronize` を含めるのは、base を後から向け直した PR と、
  既に開いていて `opened` を二度と出さない PR を取りこぼさないため（予約が付かないと、CI 緑・
  衝突なしのまま**無反応で入らない**。エラーが出ないので気づけない）。`--auto` は冪等。
- **ブランチ掃除**（`.github/workflows/cleanup-merged-branches.yml`）: `GITHUB_TOKEN` 起点の自動マージは
  後続イベントを発火しないため `--delete-branch` も `delete_branch_on_merge` も効かない。
  schedule はこの抑制の対象外なので、そちらで消す。
- 自動マージのトグルは `scripts/automerge.sh`（`on` / `off` / `status`）。`on` は `allow_auto_merge` と
  `delete_branch_on_merge` を両方立て、`status` は両方を表示する。

## 仕様書鮮度チェック（pre-commit）

- `scripts/check-spec-freshness.sh` が、監視対象コード（`WATCH_PATTERNS`）を変更したのに
  `docs/specification/` を更新していないコミットをブロックする。
- 有効化は `.githooks/` を `core.hooksPath` に設定する方式（husky は使わない）。
  **別クローンでは `git config core.hooksPath .githooks` を再実行する必要がある**（README のセットアップ手順参照）。
- 仕様変更でない場合は `git commit --no-verify` でスキップ可能。

## 自動マージ

PR を作るだけで「CI 緑 → 自動マージ → ブランチ削除」まで無人で進む。

| ワークフロー | 役割 |
|---|---|
| `.github/workflows/auto-merge.yml` | PR の open / reopen / ready_for_review で auto-merge を予約（draft は除外） |
| `.github/workflows/cleanup-merged-branches.yml` | マージ済みブランチを毎日 00:00 JST に削除 |

前提として、リポジトリ設定の `allow_auto_merge` と main 保護 ruleset の
`required_status_checks`（CI のジョブ名）を有効にしてある。**必須チェックが無いと
`--auto` は待つ対象が無く即マージになる**ため、両方揃って初めて「緑を待つ」動作になる。

掃除を別ワークフローに分けているのは、`GITHUB_TOKEN` 起点のマージが
`push` / `pull_request closed` を発火せず、`--delete-branch` も
`delete_branch_on_merge` も効かないため（schedule はこの制約を受けない）。
