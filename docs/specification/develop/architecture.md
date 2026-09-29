# アーキテクチャ

副作用（外部コマンド実行）を `collect.py` に隔離し、解析ロジックを純粋関数（`parse.py`）に
分けることで、テスト時は `collect` をモックするだけで macOS 非依存に検証できる構成。

## レイヤ構成

| モジュール | 役割 | 副作用 |
|-----------|------|--------|
| `collect.py` | `top` / `ps` / `sysctl` / `memory_pressure` / `lsof` / `launchctl` で状況を読む薄い I/O 層。読むだけで何も変えない | あり（subprocess） |
| `control.py` | プロセスの停止（`send_signal` = `os.kill`）と自 PID 取得（`current_pid`）。取り消せない副作用をここに閉じる | あり（os.kill） |
| `parse.py` | top・memory_pressure の出力を解析する純粋関数群 | なし |
| `models.py` | 型の置き場。ドメインモデル（`Process` / `PsEntry` / `ProcessGroup` / `SystemMemory` / `Origin`）・表示の種類（`View`）と判定ロジック | なし |
| `constants.py` | 定数の唯一の置き場（しきい値・コマンド名・`--help` の説明文）。実装のファイル・型の置き場には定数を置かない | なし |
| `origin.py` | 作業ディレクトリ・launchd ジョブ名から由来（`Origin`）を決める（`repo_root` / `resolve`）と、止めるときに bootout へ渡すサービス名（`launchd_service`。`<ドメイン>/<ラベル>`。GUI アプリの自動ラベルと `com.apple.*` は除く。`Process.launchd_service` に入り、止め方の案内に使う）。worktree は `.git` ファイルの gitdir をたどって本体のリポへ寄せる | あり（ファイルシステムの読み取りのみ） |
| `group.py` | アプリ名の決め方（`app_label` / `group_label`）と、それをキーにしたアプリ別の集約（`group_processes`） | なし |
| `aggregate.py` | プロセスを名前で束ねて合計し順位を付ける（`bucket_processes`）。アプリ別・PJ 別で共有 | なし |
| `report.py` | `collect` × `parse` を組み合わせて一覧・システム状況を構築 | あり（collect 経由） |
| `render.py` | `Process` / `SystemMemory` を表 / JSON に整形（`format_mb` 等の整形関数もここ） | なし（出力のみ） |
| `cli.py` | typer エントリ・オプション制御（`_option_error`）・表示の振り分け（`_render_view` が通常表示と `--watch` の唯一の入口）・`--kill` の対話（停止は control に委譲） | あり（UI 入出力のみ） |

## データフロー

```
cli.main
  └─ report.build_processes(count, grep)
       ├─ collect.top_sample(sample_count)          # top ワンショット
       ├─ parse.parse_top_processes(raw)            # (pid, mem_mb, cpu) 抽出
       ├─ collect.ps_command(pid)                   # フルコマンド
       ├─ collect.ps_rss_mb(pid)                    # ps RSS(MB)
       └─ report._annotate(processes)               # 表示分だけに PJ・起動を付ける
            ├─ collect.process_cwds(pids)           # lsof -a -d cwd -p <pids> -Fpn（1 回）
            ├─ collect.launchd_jobs()               # launchctl list（1 回。ドメインは collect.launchd_domain）
            ├─ collect.process_elapsed(pids)        # ps -o pid=,etime=（1 回）
            └─ origin.resolve(cwd, label)           # git リポ名 → launchd ジョブ名 → None
     → list[Process], top の生出力
  └─ report.build_system_memory(top_raw)
       ├─ parse.parse_phys_mem(top_raw)             # PhysMem 行（top 生出力を再利用）
       ├─ collect.swap_usage()                      # sysctl vm.swapusage
       └─ parse.parse_free_percentage(memory_pressure())
     → SystemMemory
  └─ render.render_table(...) / render.build_json(...)
```

`--group` 指定時（アプリ単位の集約）:

```
cli.main
  └─ report.build_groups(count, grep)
       ├─ collect.ps_snapshot()                     # pid/ppid/rss/command を 1 回で一括取得
       ├─ parse.parse_ps_snapshot(raw)              # pid -> PsEntry
       ├─ collect.top_sample(プロセス数 + 余裕)      # 走査幅は ps の実数から決める
       └─ group.group_processes(processes, snapshot)
            └─ group.group_label(pid, snapshot)     # 親をたどりアプリ名を決める
     → list[ProcessGroup], top の生出力
  └─ render.render_group_table(...) / render.build_group_json(...)
     （PJ 別は render.render_project_table / render.build_project_json。表の本体は _render_totals を共有）
```

`--project` 指定時（PJ 別の合計）: `report.build_projects` が `--group` と同じ全プロセス走査
（`report._scan_all`）を使い、`report._with_origins` で PJ 列と同じ由来を付けてから
`aggregate.bucket_processes` で束ねる。`--group` の `group_processes` も同じ `bucket_processes` に
キー（`group_label`）を渡しているだけなので、合計・並べ方の規則は 1 か所にある。
PJ の表記は `origin.label` が正本（PJ 列の表示と束ねるキーが同じ文字列になる）。
PJ 不明のプロセスは順位に入れず、別の `ProcessGroup` として返す。

`--app <label>` 指定時（アプリの内訳）: `report.build_app_processes` が同じ `group_label` で
所属を判定し、プロセス単位の表（`render.render_table`）に落とす。
```

## 設計判断

- **`top` の生出力を使い回す**: `build_processes` が返す top 生出力から PhysMem 行も取り出し、
  `build_system_memory` に渡すことで top の二重起動を避ける。
- **エラーは握り潰さず空を返す**: `collect._run` は `OSError` / `ValueError` を捕捉して空文字を返し、
  取得できたぶんだけ表示する（診断ツールとして「一部欠損でも動く」ことを優先）。
- **読む I/O と止める副作用を分ける**: 外部コマンドで状況を読むのは collect.py、プロセス停止の `os.kill` は
  control.py の `send_signal` に閉じ、
  `ProcessLookupError` / `PermissionError` を `"not_found"` / `"denied"` の結果コードに翻訳して返す。
  cli.py は結果コードに応じてメッセージを出すだけ（副作用を持たない）。整形（`format_mb`）は解析(parse)ではなく
  render に置く。この分離により kill/整形とも純粋 or モック可能で単体テストできる。
- **集約は親子関係で行う（コマンド名の一致ではない）**: Chromium ヘルパーの実行ファイル名は
  起動元アプリと無関係（例: ixBrowser 配下の実体は `Chromium.app`）なので、名前で束ねると
  別アプリとして散る。`group_label` は最上位の祖先まで遡り、シェル・端末・多重化ツール
  （`constants.TRANSPARENT`: zsh / tmux 等）でない最初のものをアプリとみなす。この「器は素通りする」
  規則が無いと、tmux 配下の CLI が全部 tmux に吸われる（実測でそうなった）。
- **内訳（`--app`）も ancestry で絞る**: `-g` はコマンド文字列の部分一致なので、実行ファイル名に
  親アプリ名を含まない子プロセス（`node .../mcp-server` 等）を取りこぼす。合計と内訳で判定規則が
  食い違うと「合計 15.9G と出たのに内訳を開くと 1.6G しか出ない」が起きるため、両者とも
  `group.group_label` を使う。
- **`ProcessGroup` は合計・件数・最大単体を持たない**: すべて `members` から導出する
  （導出可能な冗長フィールドを持たない = 合計だけ更新して件数が古い、が起こらない）。
- **`--group` は ps を 1 回にまとめる**: 数百プロセスが対象なので、PID ごとに `ps` を叩くと
  呼び出しがプロセス数の 2 倍に膨らむ。`collect.ps_snapshot()` の一括取得に置き換える
  （プロセス単位の既存経路は従来どおり PID ごとに引く）。
- **フィルタ時は多めにサンプリング**: `-g` 指定時は取り漏らしを防ぐため top を `count * 4`（最低 40 件）
  取得してから絞り込む。`--group` は分散の可視化が目的のため、`ps` の実プロセス数（+ `GROUP_SAMPLE_MARGIN`）を
  走査幅にする。固定上限で切ると、あふれた分が黙って合計から落ちて目的が崩れるため
  （実測 1065 プロセスのマシンで、上限 500 では合計の半分が消えた）。下限は `GROUP_SAMPLE_MIN = 100`。
