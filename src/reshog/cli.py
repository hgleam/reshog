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

from . import __version__, control, render, report
from .constants import COMMAND_BY_SORT, CPU_HELP, MEM_HELP
from .models import Process, View


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
    if pid <= 1 or pid == control.current_pid():
        console.print("[red]その PID は停止できません(システム/自分自身)。[/red]")
        raise typer.Exit(code=1)

    sig = signal.SIGKILL if force else signal.SIGTERM
    console.print(f"[dim]{label}[/dim]")
    if not assume_yes and not typer.confirm(
        f"PID {pid} を {sig.name} で停止します。よいですか?"
    ):
        console.print("中止しました。")
        return
    result = control.send_signal(pid, sig)
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

        併用制約を先に検査し、表示の種類を決めて `_render_view` に渡す。
        """
        console = Console()

        error = _option_error(sort, group_by_app, by_project, app, kill, watch, json_out)
        if error:
            console.print(f"[red]{error}[/red]")
            raise typer.Exit(code=1)

        view = _view_of(group_by_app, by_project, app)
        if watch is not None:
            _run_watch(console, view, count, grep, sort, app, watch)
            return

        processes = _render_view(console, view, count, grep, sort, app, json_out)
        if kill:
            _kill_process(processes, console, force, assume_yes)

    return cli


def _option_error(
    sort: str,
    group_by_app: bool,
    by_project: bool,
    app: str | None,
    kill: bool,
    watch: float | None,
    json_out: bool,
) -> str | None:
    """オプションの組み合わせを検査し、使えなければその理由を返す。

    外部コマンドを叩く前に落とす(CI の Linux でもこの経路は検証できる)。

    Returns:
        エラーメッセージ。問題が無ければ None。
    """
    if sort not in ("mem", "cpu"):
        return "--sort は mem か cpu を指定してください。"
    if group_by_app and app is not None:
        return "--group と --app は併用できません(合計か内訳かを選んでください)。"
    if by_project and (group_by_app or app is not None or kill):
        return (
            "--project は --group / --app / --kill と併用できません"
            "(合計の束ね方は 1 つ、停止対象は PID で選ぶため)。"
        )
    if group_by_app and kill:
        return "--group は --kill と併用できません(停止対象は PID で選ぶ必要があるため)。"
    if watch is not None and (json_out or kill):
        return "--watch は --json / --kill と併用できません。"
    return None


def _view_of(group_by_app: bool, by_project: bool, app: str | None) -> View:
    """オプションから表示の種類を決める(併用制約は検査済みの前提)。"""
    if by_project:
        return "project"
    if group_by_app:
        return "group"
    if app is not None:
        return "app"
    return "processes"


def _render_view(
    console: Console,
    view: View,
    count: int,
    grep: str | None,
    sort: str,
    app: str | None,
    json_out: bool = False,
    clear: bool = False,
) -> list[Process]:
    """表示を 1 回組み立てて出す(通常表示と --watch の唯一の入口)。

    **データを集め終えてから画面を消す。** 全プロセスを走査する表示(--group / --project)は
    数秒〜数十秒かかるので、先に消すとその間ずっと画面が空になる。

    Args:
        console: 出力先 Console。
        view: 表示の種類。
        count: 表示件数(集約ならグループ数)。
        grep: フィルタ文字列(集約では合算前に掛かる)。
        sort: 並べる基準("mem" または "cpu")。
        app: view="app" のときのアプリ名。
        json_out: True なら JSON を出す。
        clear: True なら描画の直前に画面を消す(--watch)。

    Returns:
        表示したプロセス(--kill の選択肢)。集約の表示では空。
    """
    if view == "project":
        projects, unknown, top_raw = report.build_projects(count, grep, sort)
    elif view == "group":
        groups, top_raw = report.build_groups(count, grep, sort)
    elif view == "app":
        processes, top_raw = report.build_app_processes(app or "", count, sort)
    else:
        processes, top_raw = report.build_processes(count, grep, sort)
    system = report.build_system_memory(top_raw)
    cpu = report.build_system_cpu(top_raw)

    if clear:
        console.clear()
    if view == "project":
        if json_out:
            typer.echo(render.build_project_json(projects, unknown, system, cpu))
        else:
            render.render_project_table(console, projects, unknown, system, cpu, grep, sort)
        return []
    if view == "group":
        if json_out:
            typer.echo(render.build_group_json(groups, system, cpu))
        else:
            render.render_group_table(console, groups, system, cpu, grep, sort)
        return []
    if json_out:
        typer.echo(render.build_json(processes, system, cpu))
    else:
        render.render_table(console, processes, system, cpu, sort)
    return processes


def _run_watch(
    console: Console,
    view: View,
    count: int,
    grep: str | None,
    sort: str,
    app: str | None,
    interval: float,
) -> None:
    """--watch: 一定間隔で画面を再描画し続ける。

    Args:
        console: 出力先 Console。
        view: 表示の種類。
        count: 表示件数。
        grep: フィルタ文字列。
        sort: 並べる基準("mem" または "cpu")。
        app: view="app" のときのアプリ名。
        interval: 更新間隔(秒)。
    """
    try:
        while True:
            _render_view(console, view, count, grep, sort, app, clear=True)
            console.print(f"[dim]{interval:g}秒ごとに更新 / Ctrl-C で終了[/dim]")
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n終了しました。")


app = _build_app(COMMAND_BY_SORT["mem"], "mem", MEM_HELP)
cpu_app = _build_app(COMMAND_BY_SORT["cpu"], "cpu", CPU_HELP)


if __name__ == "__main__":
    app()
