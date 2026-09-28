# reshog

[![CI](https://github.com/hgleam/reshog/actions/workflows/ci.yml/badge.svg)](https://github.com/hgleam/reshog/actions/workflows/ci.yml)

macOS の**実メモリ(物理フットプリント)を最も食っているプロセスを特定して提示する**診断 CLI。

## なぜ必要か

`ps aux` の RSS は **Metal/MPS（Apple Silicon の GPU 共有＝ユニファイドメモリ）を数えない**。
そのため ComfyUI 等の ML 系 Python は RSS 上「数十 MB」に見えるのに、実際は数十 GB を常駐している。
Activity モニタが示す本当の値＝`top` の MEM 列（物理フットプリント）。

reshog はこの物理フットプリントでランク付けし、`ps` の RSS との乖離が大きいプロセスに
**`⚠ GPU/Metal常駐(psに出ない)`** 印を付けて「小さく見えるのに実は巨大」を炙り出す。

「小さく見えるのに実は巨大」はもう 1 つある。**Chromium 系ブラウザや MCP サーバは
ヘルパープロセスへ分散するため、1 プロセスずつ見ると上位から消える**（実測: あるブラウザが
122 プロセスに割れて合計 15.9G）。`--group` は親子関係をたどってアプリ単位に合算する。

```
アプリ別 実メモリ合計 (ヘルパープロセスを親子関係で合算)
  #  合計MEM  件数  最大単体  最大PID  APP
  1    15.9G   122      1.6G    66385  ixBrowser
  2     7.9G     1      7.9G    53893  com.apple.Virtualization.VirtualMachine
  3     5.3G    18      743M    95980  claude
  4     2.9G     2      2.8G    40994  koekaki  ⚠ GPU/Metal常駐(psに出ない)
```

同じ「分散して埋もれる」問題は **CPU** にもある。1 プロセスずつ見れば数 % でも、同じものが
何十個も動いていれば合計は跳ねる。そのための入口が **`cpuhog`**（`memhog --sort cpu` と同じ）。
`--group` と併せるとアプリ単位の CPU 合計が見える（`memhog` 側でも合計 CPU は常に併記する）。

`memhog` と `cpuhog` は **`--sort` の既定値だけが違う同一の CLI**で、オプション一式は同じ。

```
$ cpuhog --group

アプリ別 CPU合計 (ヘルパープロセスを親子関係で合算)
  #  合計MEM  合計CPU  件数  最大単体  最大PID  APP
  1      17M      149     1       149    48568  PerfPowerServices
  2     4.9G     18.3    57       8.3    79022  claude
  3     4.2G     16.2     1      16.2      932  com.apple.Virtualization.VirtualMachine
```

システムの CPU 状況（Load Avg 1/5/15 分平均と user / sys / idle の内訳）も併記する。
**sys が user を大きく上回るとき**は、個々のプロセスの計算ではなくカーネル側の処理
（プロセス生成の嵐・I/O・ページング）を疑う手がかりになる。

詳しい仕様は [`docs/specification/`](docs/specification/README.md)（[依頼者向け](docs/specification/client/README.md) / [開発者向け](docs/specification/develop/README.md)）を参照。

```
== システムメモリ ==
  PhysMem: 63G used (7613M wired, 32G compressor), 217M unused.
  Swap: total = 32768.00M  used = 31855.94M  free = 912.06M
  空き: 37%

  実メモリ上位 (物理フットプリント = Activity モニタ「メモリ」相当)
    #    MEM   psRSS  %CPU    PID         起動  PJ              COMMAND
    1  32.0G     26M   0.0  28632  09-28 09:12  ComfyUI         .../Python main.py --port 8188  ⚠ GPU/Metal常駐(psに出ない)
    2   7.9G    2.6G   0.0  69624  09-25 18:45  -               com.apple.Virtualization.VirtualMachine
    3   6.6G     12M   0.0  29473  09-28 10:42  tokyo-calendar  llama-server ...              ⚠ GPU/Metal常駐(psに出ない)
```

**起動**はプロセスの開始時刻、**PJ** はどのプロジェクトから動いているか。PJ は作業ディレクトリの
git リポ名（worktree なら元のリポ名）、リポの外で動く常駐ジョブは `launchd:<ジョブ名>`、
どちらも分からないもの（GUI アプリ・root のプロセス等）は `-`。

合計は共有メモリの重複計上を含みうる**上限寄りの推定値**で、順位付けのための指標。
内訳は `memhog --app '<APP名>'` で開く。

## 使い方

```bash
memhog                 # 実メモリ上位15件
memhog -n 30           # 上位30件
memhog -g python       # フルコマンドに "python" を含むものだけ
memhog --group         # アプリ単位に合算（ヘルパーへ分散して埋もれるものを炙り出す）
memhog --app ixBrowser # そのアプリの内訳（--group の APP 名を指定）
memhog --project       # プロジェクト（git リポ / launchd ジョブ）ごとに合算。どの PJ が一番食っているか
memhog --json          # 機械可読 JSON（他スクリプト/通知連携/定期実行向け）
memhog --watch 2       # 2秒ごとに更新し続ける監視モード（Ctrl-C で終了）
memhog --kill          # 一覧から PID を選んで停止（既定で確認、不可逆操作）
memhog --kill --force  # SIGKILL で停止
```

## セットアップ

### 開発（Poetry）

```bash
cd reshog
python -m venv .venv          # .venv を先に作る（pyenv グローバル汚染を防ぐ）
poetry install
git config core.hooksPath .githooks   # pre-commit フック（仕様書鮮度チェック）を有効化
poetry run pytest             # テスト
poetry run ruff check .       # lint
poetry run mypy src           # 型チェック
poetry run memhog             # 実行
```

> `core.hooksPath` はローカル git 設定でコミットされない。**クローンごとに上記 `git config core.hooksPath .githooks` を一度実行**すること（`src/reshog/` 等を変更したのに `docs/specification/` を更新していないコミットをブロックする）。

### グローバル実行（pipx）

```bash
pipx install --editable /path/to/reshog   # 開発中の即反映
pipx install /path/to/reshog              # 通常インストール
memhog                                    # どこからでも
```

## CI / auto-merge

- PR / main への push で GitHub Actions（`test` ジョブ = genesis 監査 + doc 整合 + ruff + mypy + pytest）が走る。main 保護 ruleset で `test` を必須チェックにしているため、緑にならないとマージできない。
- 自動マージのトグル:
  ```bash
  scripts/automerge.sh status        # 現在の状態（auto-merge / branch-delete）
  scripts/automerge.sh on            # 有効化
  scripts/automerge.sh off           # 無効化（手動マージのみ）
  gh pr merge <N> --auto --squash    # ON 時: CI 緑で自動マージ予約
  ```

## ディレクトリ構成

```
.
├── README.md
├── pyproject.toml                  # Poetry（依存・entry point memhog / cpuhog）
├── .claude/
├── .githooks/
├── .github/
├── docs/                           # 仕様書 / 設計メモ（構成図は docs/README.md）
├── scripts/
├── src/
└── tests/
```

## 対応環境

macOS 専用（`top` / `ps` / `sysctl` / `memory_pressure` に依存）。
テストは `top`/`ps` をモックするため CI（Linux ランナー）でも動く。
