# CLI オプション

エントリポイント: `reshog.cli:app`（`memhog`）と `reshog.cli:cpu_app`（`cpuhog`）。
定義は `src/reshog/cli.py`。

## 2 つのコマンドの作り方（`_build_app`）

`memhog` と `cpuhog` は **`--sort` の既定値だけが違う同一の CLI**。オプションの宣言は
`_build_app(program, default_sort, help_text)` の中に 1 つだけ置き、既定値と説明文を
引数で差し替える。

```python
app     = _build_app("memhog", "mem", MEM_HELP)
cpu_app = _build_app("cpuhog", "cpu", CPU_HELP)
```

- **`@app.command()` を 2 つ並べて書かない。** 片方にオプションを足し忘れても何も壊れず、
  `--help` の差として静かに残る。ファクトリなら構造的に同じものしか作れない。
- **実行時に argv を書き換えて既定を変える方式は採らない。** `cpuhog --help` が `--sort` の
  既定を `mem` と表示してしまい、ヘルプが嘘をつく。
- **並び順とコマンド名の対応は `constants.COMMAND_BY_SORT` が唯一の正本**
  （`{"mem": "memhog", "cpu": "cpuhog"}`）。pyproject の entry point・`_build_app` の
  app 生成・`render` の提案文がこれを参照する。3 箇所に別々に書くと、コマンドを増やしたとき
  提案文だけ古いまま残る。entry point との一致は `tests/test_render.py` で固定する。
- `--version` は `_make_version_callback(program)` で自分のコマンド名を名乗る。
- `--help` の本文は `@cli.command(help=help_text)` に渡す（関数の docstring は実装の説明用）。
  2 つの入口があっても説明が同じでは、利用者が違いを判断できない。

## オプション一覧

| オプション | 短縮 | 既定 | 説明 |
|-----------|------|------|------|
| `--count` | `-n` | `15` | 表示する件数 |
| `--sort` | | コマンド依存 | 並べる基準（`mem` = 実メモリ / `cpu` = CPU 使用率）。既定は `memhog` なら `mem`、`cpuhog` なら `cpu` |
| `--grep` | `-g` | なし | フルコマンドへの部分一致で絞り込み（大小無視） |
| `--json` | | `False` | 機械可読な JSON で出力 |
| `--group` | | `False` | プロセス単位でなくアプリ単位に合算して表示 |
| `--app` | | なし | 指定したアプリ名に属するプロセスだけを一覧（`--group` の内訳） |
| `--project` | | `False` | プロジェクト（git リポ / launchd ジョブ）ごとに合算して表示 |
| `--watch` | | なし | 指定秒間隔で画面を更新し続ける（監視モード） |
| `--kill` | | `False` | 一覧から PID を選んで停止 |
| `--force` | | `False` | `--kill` 時に SIGKILL を使う（既定は SIGTERM） |
| `--yes` | `-y` | `False` | `--kill` の確認プロンプトを省略 |
| `--version` | | | バージョンを表示して終了 |

## 併用制約・挙動

- `--sort` は `mem` / `cpu` 以外を渡すとエラー終了 code 1。
- `--sort` は表示側の並べ替えではなく **`top` の `-o` を切り替える**。取得後に並べ替えると
  母集団が「メモリ上位 N 件」のままになり、CPU 上位のプロセスがそもそも含まれない。
  `--group` / `--app` にも同じ値を渡す（集約の並び順・グループ内の最大単体の選び方に効く）。
- `--watch` は `--json` / `--kill` と**併用不可**（指定時はエラー終了 code 1）。
- `--watch`: 無限ループで `_render_view(..., clear=True)` → `sleep(interval)`。`_render_view` は
  **データを集め終えてから** `console.clear()` して描画する（全プロセスを走査する `--group` / `--project` は
  数秒〜数十秒かかるため、先に消すとその間画面が空になる）。`Ctrl-C`（KeyboardInterrupt）で終了。
  通常表示と `--watch` は同じ `_render_view` を通る（表示を足すとき 1 か所だけ直せばよい。
  `tests/test_structure.py` が `report.build_*` の呼び出し元を 1 関数に固定）。
- `--kill`（`_kill_process`、**不可逆操作**）:
  - 既定の停止対象 PID は一覧の先頭（最大消費元）。プロンプトで PID を入力。
  - `pid <= 1` または自分自身（`control.current_pid()`）は停止拒否（code 1）。
  - `--yes` 未指定なら `PID N を SIG… で停止します。よいですか?` を確認。
  - 実際の送信は `control.send_signal(pid, sig)`（停止の副作用は control 層）。戻り値で分岐:
    `"not_found"` → 「既に終了?」表示。`"denied"` → 「権限がありません」で code 1。`"ok"` → 送信済み表示。
- `--group` は `--kill` / `--app` と**併用不可**（いずれもエラー終了 code 1）。`--kill` は停止対象を
  PID で選ぶ必要があるため、`--app` は「合計か内訳か」が排他のため。
- `--app` は所属判定を `group.group_label`（親子関係）で行う。`-g`（コマンド文字列の部分一致）では
  実行ファイル名に親アプリ名を含まない子プロセス（MCP サーバ等）を取りこぼすため、集約と同じ規則を使う。
  出力はプロセス単位の表（`render.render_table`）で、`--kill` / `--json` / `--watch` と併用できる。
- `--group` の `-n` は「表示するグループ数」、`-g` は**合算前**のプロセスに掛かる
  （一致したプロセスだけが合計に入る）。この場合は部分合計であることを表の見出しに出す。`--watch` とは併用可。
- `--json`: `render.build_json` の出力（`system` と `processes[]`、各要素に `hidden_gpu` を含む）。
  各要素の `origin` は `{"kind": "git" | "launchd", "name": ...}` か `null`、`started_at` は
  ローカル時刻の ISO 8601（秒まで）か `null`。`launchd_job` は面倒を見ている launchd のジョブ名か `null`。
- 停止の案内は `render.stop_command(process)` が唯一の正本（表の下の案内と `--kill` の警告の両方が使う）。
  launchd のジョブなら `launchctl bootout gui/$(id -u)/<shlex.quote したラベル>`、それ以外は `kill <PID>`。
- 開始時刻は `ps` の `etime`（経過時間）から「いま − 経過」で出す。`lstart` は曜日・月名が
  ロケールで変わるため使わない。
- `--group --json`: `render.build_group_json` の出力（`system` と `groups[]`。各要素は
  `label` / `total_mb` / `count` / `hidden_gpu` / `largest{pid, mem_mb, command}`）。
- `--project --json`: `render.build_project_json` の出力。`groups[]` の代わりに `projects[]`
  （各要素の形は `groups[]` と同じ）と、`unknown`（PJ 不明の `{total_mb, total_cpu, count}` か `null`）。
- `--project` は `--group` / `--app` / `--kill` と**併用不可**（code 1）。合計の束ね方は 1 つしか
  選べず、停止対象は PID で選ぶため。表の下の提案は出さない（`--app` は APP 名しか受け取らない）。
