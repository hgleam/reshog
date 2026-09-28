"""typer エントリポイント。

同じ CLI を **既定の並び順だけ変えた 2 つのコマンド**として公開する。

    memhog … 実メモリ順(--sort mem)
    cpuhog … CPU 順(--sort cpu)

オプションの宣言は `_build_app` の中に 1 つだけ置き、既定値を引数で差し替える。
`@app.command()` を 2 つ並べて書くと、片方にオプションを足し忘れても何も壊れず
`--help` の差として静かに残る。ファクトリなら**構造的に同じものしか作れない**。

実行時に argv を書き換えて既定を変える方式は採らない。`cpuhog --help` が `--sort` の
既定を mem と表示してしまい、**ヘルプが嘘をつく**。
"""

import signal
import time
from collections.abc import Callable

import typer
from rich.console import Console

from . import __version__, collect, render, report
from .models import COMMAND_BY_SORT, Process

# 各コマンドの説明。--sort の既定以外は同じ CLI なので、違いが分かるように書き分ける。
_MEM_HELP = """macOS の実メモリ(物理フットプリント)を食っているプロセスを特定して提示する。

ps の RSS は Metal/MPS(GPU 共有メモリ)を数えないため、ComfyUI 等の ML 系は小さく見える。
top の物理フットプリントでランクし、その乖離を「⚠ GPU/Metal常駐」印で炙り出す。

CPU 順で見るなら cpuhog(または --sort cpu)。"""

_CPU_HELP = """macOS の CPU を食っているプロセスを特定して提示する。

1 プロセスずつ見ると数 % でも、同じものが何十個も動いていれば合計は跳ねる。
--group はヘルパープロセスを親子関係で合算するので、分散して埋もれる消費が見える。

sys が user を大きく上回るときは、個々のプロセスの計算ではなくカーネル側の処理
(プロセス生成の嵐・I/O・ページング)を疑う。

実メモリ順で見るなら memhog(または --sort mem)。"""


def _make_version_callback(program: str) -> Callable[[bool], None]:
    """`--version` で自分のコマンド名を名乗るコールバックを作る。

    Args:
        program: 名乗るコマンド名("memhog" / "cpuhog")。

    Returns:
        typer の is_eager コールバック。
    """

    def _callback(value: bool) -> None:
        if value:
            typer.echo(f"{program} {__version__}")
            raise typer.Exit()

    return _callback


def _kill_process(
    processes: list[Process], console: Console, force: bool, assume_yes: bool
) -> None:
    """一覧から PID を選んで停止する(不可逆操作のため既定で確認する)。

    Args:
        processes: 表示済みのプロセス一覧。
        console: 出力先 Console。
        force: True なら SIGKILL、False なら SIGTERM。
        assume_yes: True なら確認プロンプトを省略する。
    """
    if not processes:
        console.print("[yellow]対象プロセスがありません。[/yellow]")
        return
    default_pid = processes[0].pid
    pid = typer.prompt("停止する PID", default=default_pid, type=int)

    target = next((p for p in processes if p.pid == pid), None)
    label = target.command if target else "(一覧外の PID)"
    if pid <= 1 or pid == collect.current_pid():
        console.print("[red]その PID は停止できません(システム/自分自身)。[/red]")
        raise typer.Exit(code=1)

    sig = signal.SIGKILL if force else signal.SIGTERM
    console.print(f"[dim]{label}[/dim]")
    if not assume_yes and not typer.confirm(
        f"PID {pid} を {sig.name} で停止します。よいですか?"
    ):
        console.print("中止しました。")
        return
    result = collect.send_signal(pid, sig)
    if result == "not_found":
        console.print(f"[yellow]PID {pid} は存在しません(既に終了?)。[/yellow]")
        return
    if result == "denied":
        console.print(f"[red]PID {pid} を停止する権限がありません(sudo が必要かも)。[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]PID {pid} に {sig.name} を送信しました。[/green]")


def _build_app(program: str, default_sort: str, help_text: str) -> typer.Typer:
    """コマンドを組み立てる(memhog / cpuhog で共有する唯一の定義)。

    Args:
        program: コマンド名。`--version` の名乗りに使う。
        default_sort: `--sort` の既定値("mem" または "cpu")。
        help_text: コマンドの説明(`--help` の冒頭)。

    Returns:
        組み立てた typer アプリ。
    """
    cli = typer.Typer(add_completion=False, help=help_text)

    @cli.command(help=help_text)
    def main(
        count: int = typer.Option(15, "-n", "--count", help="表示する件数。"),
        sort: str = typer.Option(
            default_sort,
            "--sort",
            help="並べる基準。mem(実メモリ) または cpu(CPU使用率)。",
        ),
        grep: str | None = typer.Option(
            None, "-g", "--grep", help="フルコマンドに部分一致するものだけ表示(大小無視)。"
        ),
        json_out: bool = typer.Option(False, "--json", help="機械可読な JSON で出力する。"),
        group_by_app: bool = typer.Option(
            False,
            "--group",
            help="プロセス単位でなくアプリ単位に合算して表示する(分散して埋もれるものを炙り出す)。",
        ),
        by_project: bool = typer.Option(
            False,
            "--project",
            help=(
                "プロジェクト(作業ディレクトリの git リポ / launchd ジョブ)ごとに"
                "合算して表示する。"
            ),
        ),
        app: str | None = typer.Option(
            None,
            "--app",
            help="--group の APP 名を指定し、そのアプリに属するプロセスだけを一覧する(内訳)。",
        ),
        watch: float | None = typer.Option(
            None, "--watch", help="指定秒間隔で画面を更新し続ける(top のように監視)。"
        ),
        kill: bool = typer.Option(False, "--kill", help="一覧から PID を選んで停止する。"),
        force: bool = typer.Option(False, "--force", help="--kill 時に SIGKILL を使う。"),
        assume_yes: bool = typer.Option(False, "-y", "--yes", help="--kill の確認を省略する。"),
        _version: bool = typer.Option(
            False,
            "--version",
            callback=_make_version_callback(program),
            is_eager=True,
            help="バージョン表示。",
        ),
    ) -> None:
        """上位プロセスを表示する(--help の文面は help_text 側が正本)。

        併用制約を先に検査し、`--app` / `--group` / 通常 の 3 経路へ振り分ける。
        """
        console = Console()

        if sort not in ("mem", "cpu"):
            console.print("[red]--sort は mem か cpu を指定してください。[/red]")
            raise typer.Exit(code=1)

        if group_by_app and app is not None:
            console.print(
                "[red]--group と --app は併用できません(合計か内訳かを選んでください)。[/red]"
            )
            raise typer.Exit(code=1)

        if by_project and (group_by_app or app is not None or kill):
            console.print(
                "[red]--project は --group / --app / --kill と併用できません"
                "(合計の束ね方は 1 つ、停止対象は PID で選ぶため)。[/red]"
            )
            raise typer.Exit(code=1)

        if group_by_app and kill:
            console.print(
                "[red]--group は --kill と併用できません"
                "(停止対象は PID で選ぶ必要があるため)。[/red]"
            )
            raise typer.Exit(code=1)

        if watch is not None:
            if json_out or kill:
                console.print("[red]--watch は --json / --kill と併用できません。[/red]")
                raise typer.Exit(code=1)
            _run_watch(console, count, grep, watch, group_by_app, app, sort, by_project)
            return

        if by_project:
            _show_projects(console, count, grep, sort, json_out)
            return

        if app is not None:
            processes, top_raw = report.build_app_processes(app, count, sort)
            system = report.build_system_memory(top_raw)
            cpu = report.build_system_cpu(top_raw)
            if json_out:
                typer.echo(render.build_json(processes, system, cpu))
                return
            render.render_table(console, processes, system, cpu, sort)
            if kill:
                _kill_process(processes, console, force, assume_yes)
            return

        if group_by_app:
            groups, top_raw = report.build_groups(count, grep, sort)
            system = report.build_system_memory(top_raw)
            cpu = report.build_system_cpu(top_raw)
            if json_out:
                typer.echo(render.build_group_json(groups, system, cpu))
                return
            render.render_group_table(console, groups, system, cpu, grep, sort)
            return

        processes, top_raw = report.build_processes(count, grep, sort)
        system = report.build_system_memory(top_raw)
        cpu = report.build_system_cpu(top_raw)

        if json_out:
            typer.echo(render.build_json(processes, system, cpu))
            return

        render.render_table(console, processes, system, cpu, sort)
        if kill:
            _kill_process(processes, console, force, assume_yes)

    return cli


def _show_projects(
    console: Console, count: int, grep: str | None, sort: str, json_out: bool = False
) -> None:
    """--project: PJ 別の合計を 1 回描画する(通常表示と --watch で共有)。

    Args:
        console: 出力先 Console。
        count: 表示する PJ 数。
        grep: 合算前に掛けるフィルタ。
        sort: 並べる基準("mem" または "cpu")。
        json_out: True なら JSON を出す。
    """
    projects, unknown, top_raw = report.build_projects(count, grep, sort)
    system = report.build_system_memory(top_raw)
    cpu = report.build_system_cpu(top_raw)
    if json_out:
        typer.echo(render.build_group_json(projects, system, cpu, "project", unknown))
        return
    render.render_group_table(console, projects, system, cpu, grep, sort, "project", unknown)


def _run_watch(
    console: Console,
    count: int,
    grep: str | None,
    interval: float,
    group_by_app: bool = False,
    app: str | None = None,
    sort: str = "mem",
    by_project: bool = False,
) -> None:
    """--watch: 一定間隔で画面を再描画し続ける。

    Args:
        console: 出力先 Console。
        count: 表示件数。
        grep: フィルタ文字列。
        interval: 更新間隔(秒)。
        group_by_app: True ならアプリ単位に合算して描画する。
        app: 指定時はそのアプリに属するプロセスだけを描画する。
        sort: 並べる基準("mem" または "cpu")。
        by_project: True なら PJ 別に合算して描画する。
    """
    try:
        while True:
            if by_project:
                console.clear()
                _show_projects(console, count, grep, sort)
                console.print(f"[dim]{interval:g}秒ごとに更新 / Ctrl-C で終了[/dim]")
                time.sleep(interval)
                continue
            if group_by_app:
                groups, top_raw = report.build_groups(count, grep, sort)
                system = report.build_system_memory(top_raw)
                cpu = report.build_system_cpu(top_raw)
                console.clear()
                render.render_group_table(console, groups, system, cpu, grep, sort)
                console.print(f"[dim]{interval:g}秒ごとに更新 / Ctrl-C で終了[/dim]")
                time.sleep(interval)
                continue
            if app is not None:
                processes, top_raw = report.build_app_processes(app, count, sort)
            else:
                processes, top_raw = report.build_processes(count, grep, sort)
            system = report.build_system_memory(top_raw)
            cpu = report.build_system_cpu(top_raw)
            console.clear()
            render.render_table(console, processes, system, cpu, sort)
            console.print(f"[dim]{interval:g}秒ごとに更新 / Ctrl-C で終了[/dim]")
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n終了しました。")


app = _build_app(COMMAND_BY_SORT["mem"], "mem", _MEM_HELP)
cpu_app = _build_app(COMMAND_BY_SORT["cpu"], "cpu", _CPU_HELP)


if __name__ == "__main__":
    app()
