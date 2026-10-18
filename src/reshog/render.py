"""プロセス一覧・システム状況の出力(リッチな表 / JSON)。"""

import json
import shlex
from collections import Counter
from datetime import datetime

from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from . import known, origin
from .constants import (
    ALERT_CPU,
    ALERT_MB,
    CHURN_TOP_CHILDREN,
    CHURN_TOP_SOURCES,
    CHURN_UNKNOWN_PARENT,
    COMMAND_BY_SORT,
    LAUNCHD_PID,
    MAX_CMD,
)
from .group import app_label
from .models import (
    Churn,
    ChurnSource,
    LlmState,
    Origin,
    Process,
    ProcessGroup,
    SystemCpu,
    SystemMemory,
)


def _shorten(command: str) -> str:
    """長いコマンドを末尾省略する。

    Note:
        省略しても中身は他プロセス由来の文字列のままなので、rich の console.print へ
        渡す際は必ず `escape()` を通すこと(マークアップとして解釈させない)。
    """
    return command if len(command) <= MAX_CMD else command[: MAX_CMD - 3] + "..."


def _origin_text(found: Origin | None) -> Text:
    """PJ 列のセルを作る(表記は origin.label が正本)。

    他プロセス由来の文字列だが、Text に入れるのでマークアップとしては解釈されない。
    """
    if found is None:
        return Text("-", style="dim")
    return Text(origin.label(found), style="dim" if found.kind == "launchd" else "")


def _started_text(started_at: datetime | None) -> Text:
    """起動列のセルを作る。桁を揃えるため、今日のものも日付から出す。"""
    if started_at is None:
        return Text("-", style="dim")
    return Text(started_at.strftime("%m-%d %H:%M"))


def llm_state_text(state: LlmState) -> str:
    """llama-server の休止状態の表示(「💤 休止中(14:21 から)」「▶ 稼働中(14:14 に復帰)」)。

    Args:
        state: 休止状態。

    Returns:
        表示する文字列。その状態になった時刻が分からなければ状態だけ。
    """
    if state.sleeping:
        return "💤 休止中" + (f"({state.since:%H:%M} から)" if state.since else "")
    return "▶ 稼働中" + (f"({state.since:%H:%M} に復帰)" if state.since else "")


def stop_command(process: Process) -> str:
    """そのプロセスを止めるために打つコマンド(貼り付けてそのまま実行できる形)。

    launchd のジョブは kill しても KeepAlive で起動し直されるので、ジョブごと降ろす。
    サービス名はラベル(他プロセス由来の文字列)を含むので shell quote する。

    Args:
        process: 対象プロセス。

    Returns:
        `launchctl bootout <ドメイン>/<ラベル>` または `kill <PID>`。
    """
    if process.launchd_service:
        return f"launchctl bootout {shlex.quote(process.launchd_service)}"
    return f"kill {process.pid}"


def format_mb(mb: float) -> str:
    """MB を人間可読(G/M)に整形する。

    Args:
        mb: MB 単位の値。

    Returns:
        1024 以上なら "12.3G"、未満なら "512M"。
    """
    if mb >= 1024:
        return f"{mb / 1024:.1f}G"
    return f"{round(mb)}M"


def _render_system(console: Console, system: SystemMemory, cpu: SystemCpu) -> None:
    """システムの概況(メモリと CPU)を出力する(プロセス別 / アプリ別で共通)。

    Args:
        console: 出力先の rich Console。
        system: システム全体のメモリ状況。
        cpu: システム全体の CPU 状況。
    """
    console.print()
    console.print("[bold]== システムメモリ ==[/bold]")
    if system.phys:
        console.print(f"  PhysMem: {escape(system.phys)}")
    if system.swap:
        console.print(f"  Swap: {escape(system.swap)}")
    if system.free_percentage:
        console.print(f"  空き: {escape(system.free_percentage)}")

    console.print("[bold]== システムCPU ==[/bold]")
    if cpu.load_average:
        console.print(f"  Load Avg: {escape(cpu.load_average)}  [dim](1分 / 5分 / 15分)[/dim]")
    if cpu.usage:
        console.print(f"  内訳: {escape(cpu.usage)}")


def _system_payload(system: SystemMemory, cpu: SystemCpu) -> dict[str, str | None]:
    """システム状況を JSON 用の辞書にする(出力形式の正本を 1 箇所に保つ)。

    Args:
        system: システム全体のメモリ状況。
        cpu: システム全体の CPU 状況。

    Returns:
        JSON へそのまま入れられる辞書。
    """
    return {
        "phys": system.phys,
        "swap": system.swap,
        "free_percentage": system.free_percentage,
        "load_average": cpu.load_average,
        "cpu_usage": cpu.usage,
    }


def render_table(
    console: Console,
    processes: list[Process],
    system: SystemMemory,
    cpu: SystemCpu,
    order: str = "mem",
) -> None:
    """人間向けに表形式で出力する。

    Args:
        console: 出力先の rich Console。
        processes: 表示するプロセス一覧(order で指定した資源の降順)。
        system: システム全体のメモリ状況。
        cpu: システム全体の CPU 状況。
        order: 並べた基準。"mem" または "cpu"。見出しと強調色に反映する。
    """
    _render_system(console, system, cpu)

    by_cpu = order == "cpu"
    table = Table(
        title=(
            "CPU 上位 (直近サンプル間の使用率。100% = 1 コア分)"
            if by_cpu
            else "実メモリ上位 (物理フットプリント = Activity モニタ「メモリ」相当)"
        ),
        title_style="bold",
        title_justify="left",
        header_style="dim",
        expand=False,
    )
    table.add_column("#", justify="right")
    table.add_column("MEM", justify="right")
    table.add_column("psRSS", justify="right")
    table.add_column("%CPU", justify="right")
    table.add_column("PID", justify="right")
    table.add_column("起動", justify="right")
    table.add_column("PJ")
    table.add_column("COMMAND")

    for rank, p in enumerate(processes, start=1):
        alert = p.cpu >= ALERT_CPU if by_cpu else p.mem_mb >= ALERT_MB
        row_style = "red" if alert else ""
        cmd = Text(_shorten(p.command), style=row_style)
        if p.hidden_gpu:
            cmd.append("  ⚠ GPU/Metal常駐(psに出ない)", style="yellow")
        about = known.describe(p.command)
        if about is not None:
            note = about.purpose if about.stoppable else f"{about.purpose}・止めない"
            cmd.append(f"  ⓘ {note}", style="cyan")
        if p.llm_state is not None:
            cmd.append(
                f"  {llm_state_text(p.llm_state)}",
                style="dim" if p.llm_state.sleeping else "green",
            )
        table.add_row(
            str(rank),
            format_mb(p.mem_mb),
            format_mb(p.rss_mb),
            f"{p.cpu:g}",
            str(p.pid),
            _started_text(p.started_at),
            _origin_text(p.origin),
            cmd,
            style=row_style,
        )
    console.print(table)

    if processes:
        top = processes[0]
        console.print("[bold]== 最大の消費元 ==[/bold]")
        amount = f"{top.cpu:g}%CPU" if by_cpu else format_mb(top.mem_mb)
        console.print(f"  [green]PID {top.pid} / {amount}[/green]")
        console.print(f"  [dim]{escape(_shorten(top.command))}[/dim]")
        about = known.describe(top.command)
        if about is not None:
            console.print(f"  [cyan]これは: {escape(about.purpose)}[/cyan]")
            console.print(f"  [cyan]{escape(about.advice)}[/cyan]")
        # 止めてはいけないもの(WindowServer 等)には停止の案内を出さない。
        if about is None or about.stoppable:
            # 提案するのは「いま見ている並び順を再現するコマンド」。invoke されたコマンド名を
            # そのまま使うと、memhog --sort cpu で見ているのに memhog --kill を勧めることになり、
            # 開き直した画面の並びが変わる。
            console.print(
                f"  停止するなら:  [bold]{COMMAND_BY_SORT[order]} --kill[/bold]"
                f"  または  [bold]{escape(stop_command(top))}[/bold]"
            )
            if top.launchd_service:
                domain = origin.service_domain(top.launchd_service)
                console.print(
                    "  [dim]launchd の常駐ジョブなので、kill しても起動し直されることがある"
                    f"(戻すときは launchctl bootstrap {escape(domain)} <plist のパス>)[/dim]"
                )
    console.print()


def render_churn(console: Console, found: Churn | None) -> None:
    """短命プロセスの本数と、それを生んでいる起動元の内訳を出す(cpuhog の全表示で共通)。

    Args:
        console: 出力先の rich Console。
        found: 集計結果。数えられなかったら None(「0 本」と区別して出す)。
    """
    if found is None:
        console.print("[bold]== 短命プロセス ==[/bold]")
        console.print("  [yellow]数えられませんでした(ps が読めなかった)。[/yellow]")
        return
    console.print(
        f"[bold]== 短命プロセス ({found.seconds:.1f} 秒間に新しく生まれたもの) ==[/bold]"
    )
    console.print(
        f"  {found.total} 本以上 (約 {found.per_second:.0f} 本/秒)  "
        "[dim]数秒で終わるので上の一覧の CPU には出ない。"
        "負荷平均が高いのに一覧が静かなら、ここが原因[/dim]"
    )
    if not found.sources:
        return
    table = Table(
        title="起動元(数え始めから動いていた親)ごと",
        title_style="bold",
        title_justify="left",
        header_style="dim",
        expand=False,
    )
    table.add_column("#", justify="right")
    table.add_column("本数", justify="right")
    table.add_column("PJ")
    table.add_column("起動元")
    table.add_column("PID", justify="right")
    table.add_column("主な中身")
    for rank, source in enumerate(found.sources[:CHURN_TOP_SOURCES], start=1):
        unknown = source.pid == CHURN_UNKNOWN_PARENT
        table.add_row(
            str(rank),
            str(source.count),
            _origin_text(source.origin),
            Text(_source_label(source)),
            "-" if unknown else str(source.pid),
            Text(source.main_children(CHURN_TOP_CHILDREN)),
        )
    # 表に出さない起動元の分も 1 行で足す。行の合計が見出しの本数と合うように。
    rest = found.sources[CHURN_TOP_SOURCES:]
    if rest:
        table.add_row(
            "", str(sum(s.count for s in rest)), "", f"ほか {len(rest)} 起動元", "", "", style="dim"
        )
    console.print(table)


def _source_label(source: ChurnSource) -> str:
    """起動元の列の表記。"""
    if source.pid == CHURN_UNKNOWN_PARENT:
        return "(親不明)"
    if source.pid == LAUNCHD_PID:
        # 親が先に終わった子は launchd に付け替わる。launchd が生んだと誤読させない。
        return "launchd(親が先に終わったものを含む)"
    return app_label(source.command)


def _churn_payload(found: Churn) -> dict[str, object]:
    """短命プロセスの集計を JSON 用の辞書にする。"""
    return {
        "seconds": round(found.seconds, 2),
        "total": found.total,
        "per_second": round(found.per_second, 1),
        "sources": [
            {
                "pid": None if s.pid == CHURN_UNKNOWN_PARENT else s.pid,
                "command": s.command,
                "origin": {"kind": s.origin.kind, "name": s.origin.name} if s.origin else None,
                "count": s.count,
                "children": dict(Counter(s.children).most_common()),
            }
            for s in found.sources
        ],
    }


def _dumps(payload: dict[str, object], found: Churn | None, measured: bool) -> str:
    """JSON を文字列にする(3 つの表示で共通)。

    数えたときだけ `churn` を足す。数えようとして読めなかったときは null(「0 本」と区別する)。
    """
    if measured:
        payload["churn"] = _churn_payload(found) if found is not None else None
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_json(
    processes: list[Process],
    system: SystemMemory,
    cpu: SystemCpu,
    found: Churn | None = None,
    measured: bool = False,
) -> str:
    """機械可読な JSON 文字列を生成する。

    Args:
        processes: プロセス一覧。
        system: システムのメモリ状況。
        cpu: システムの CPU 状況。
        found: 短命プロセスの集計。数えられなかった・数えていなければ None。
        measured: 数えようとしたか。False なら `churn` を出さない。

    Returns:
        整形済み JSON 文字列。
    """
    payload: dict[str, object] = {
        "system": _system_payload(system, cpu),
        "processes": [
            {
                "rank": rank,
                "pid": p.pid,
                "mem_mb": p.mem_mb,
                "rss_mb": p.rss_mb,
                "cpu": p.cpu,
                "hidden_gpu": p.hidden_gpu,
                "origin": (
                    {"kind": p.origin.kind, "name": p.origin.name} if p.origin else None
                ),
                "launchd_service": p.launchd_service,
                "llm_state": (
                    {
                        "sleeping": p.llm_state.sleeping,
                        "since": (
                            p.llm_state.since.isoformat(timespec="seconds")
                            if p.llm_state.since
                            else None
                        ),
                    }
                    if p.llm_state
                    else None
                ),
                "started_at": (
                    p.started_at.isoformat(timespec="seconds") if p.started_at else None
                ),
                "command": p.command,
            }
            for rank, p in enumerate(processes, start=1)
        ],
    }
    return _dumps(payload, found, measured)


def render_group_table(
    console: Console,
    groups: list[ProcessGroup],
    system: SystemMemory,
    cpu: SystemCpu,
    grep: str | None = None,
    order: str = "mem",
) -> None:
    """アプリ別(--group)に集約した結果を表形式で出力する。

    Args:
        console: 出力先の rich Console。
        groups: 表示するグループ(order で指定した資源の合計降順)。
        system: システム全体のメモリ状況。
        cpu: システム全体の CPU 状況。
        grep: 適用中の -g パターン。指定時は「部分合計」であることを見出しに明示する。
        order: 並べた基準。"mem" または "cpu"。
    """
    _render_totals(
        console, groups, system, cpu, grep, order,
        title="アプリ別 {resource} (ヘルパープロセスを親子関係で合算)",
        label_header="APP",
    )
    if groups:
        console.print(
            "  内訳を見るなら:  "
            f"[bold]{COMMAND_BY_SORT[order]} --app "
            f"{escape(shlex.quote(groups[0].label))}[/bold]"
        )
    console.print()


def render_project_table(
    console: Console,
    projects: list[ProcessGroup],
    unknown: ProcessGroup | None,
    system: SystemMemory,
    cpu: SystemCpu,
    grep: str | None = None,
    order: str = "mem",
) -> None:
    """PJ 別(--project)に集約した結果を表形式で出力する。

    `--app` は APP 名しか受け取らないので、内訳の提案は出さない。

    Args:
        console: 出力先の rich Console。
        projects: 表示する PJ(order で指定した資源の合計降順)。
        unknown: PJ が分からなかったプロセスの合計(順位には入れない)。無ければ None。
        system: システム全体のメモリ状況。
        cpu: システム全体の CPU 状況。
        grep: 適用中の -g パターン。
        order: 並べた基準。"mem" または "cpu"。
    """
    _render_totals(
        console, projects, system, cpu, grep, order,
        title="PJ 別 {resource} (作業ディレクトリの git リポ / launchd ジョブで合算)",
        label_header="PJ",
    )
    if unknown is not None:
        console.print(
            f"  [dim]PJ 不明(GUI アプリ・root のプロセス等): {_amount(unknown, order)}"
            f" / {unknown.count}プロセス  ※順位には入れていない[/dim]"
        )
    console.print()


def _amount(group: ProcessGroup, order: str) -> str:
    """並べた基準での合計(CPU なら %、メモリなら G/M)。"""
    return f"{group.total_cpu:g}%CPU" if order == "cpu" else format_mb(group.total_mb)


def _render_totals(
    console: Console,
    groups: list[ProcessGroup],
    system: SystemMemory,
    cpu: SystemCpu,
    grep: str | None,
    order: str,
    title: str,
    label_header: str,
) -> None:
    """集約の表と「最大の消費元」を出す(アプリ別 / PJ 別で共通の部分)。

    Args:
        console: 出力先の rich Console。
        groups: 表示するグループ。
        system: システム全体のメモリ状況。
        cpu: システム全体の CPU 状況。
        grep: 適用中の -g パターン。指定時は「部分合計」であることを見出しに明示する。
        order: 並べた基準。"mem" または "cpu"。
        title: 見出し。`{resource}` が「実メモリ合計」/「CPU合計」に置き換わる。
        label_header: 名前の列の見出し。
    """
    _render_system(console, system, cpu)

    by_cpu = order == "cpu"
    title = title.format(resource="CPU合計" if by_cpu else "実メモリ合計")
    if grep:
        title += f" ※ -g {escape(shlex.quote(grep))} 一致プロセスのみの部分合計"
    table = Table(
        title=title,
        title_style="bold",
        title_justify="left",
        header_style="dim",
        expand=False,
    )
    table.add_column("#", justify="right")
    table.add_column("合計MEM", justify="right")
    # CPU は「1 プロセスずつ見ると小さいが数が多い」形で埋もれるため、
    # メモリと並べて常に出す(どちらの基準で並べていても内訳が読める)。
    table.add_column("合計CPU", justify="right")
    table.add_column("件数", justify="right")
    table.add_column("最大単体", justify="right")
    table.add_column("最大PID", justify="right")
    table.add_column(label_header)

    for rank, g in enumerate(groups, start=1):
        alert = g.total_cpu >= ALERT_CPU if by_cpu else g.total_mb >= ALERT_MB
        row_style = "red" if alert else ""
        label = Text(g.label, style=row_style)
        if g.hidden_gpu:
            label.append("  ⚠ GPU/Metal常駐(psに出ない)", style="yellow")
        table.add_row(
            str(rank),
            format_mb(g.total_mb),
            f"{g.total_cpu:g}",
            str(g.count),
            format_mb(g.largest.mem_mb) if not by_cpu else f"{g.largest.cpu:g}",
            str(g.largest.pid),
            label,
            style=row_style,
        )
    console.print(table)

    if groups:
        top = groups[0]
        console.print("[bold]== 最大の消費元 ==[/bold]")
        console.print(
            f"  [green]{escape(top.label)} / {_amount(top, order)}"
            f" / {top.count}プロセス[/green]"
        )
        console.print(
            f"  [dim]最大単体: PID {top.largest.pid} "
            f"{escape(_shorten(top.largest.command))}[/dim]"
        )


def _group_items(groups: list[ProcessGroup]) -> list[dict[str, object]]:
    """集約結果の JSON 要素(アプリ別 / PJ 別で同じ形)。"""
    return [
        {
            "rank": rank,
            "label": g.label,
            "total_mb": g.total_mb,
            "total_cpu": g.total_cpu,
            "count": g.count,
            "hidden_gpu": g.hidden_gpu,
            "largest": {
                "pid": g.largest.pid,
                "mem_mb": g.largest.mem_mb,
                "cpu": g.largest.cpu,
                "command": g.largest.command,
            },
        }
        for rank, g in enumerate(groups, start=1)
    ]


def build_group_json(
    groups: list[ProcessGroup],
    system: SystemMemory,
    cpu: SystemCpu,
    found: Churn | None = None,
    measured: bool = False,
) -> str:
    """アプリ別の集約結果を機械可読な JSON 文字列にする。

    Args:
        groups: グループ一覧。
        system: システムのメモリ状況。
        cpu: システムの CPU 状況。
        found: 短命プロセスの集計。数えられなかった・数えていなければ None。
        measured: 数えようとしたか。False なら `churn` を出さない。

    Returns:
        整形済み JSON 文字列(`system` と `groups[]`)。
    """
    payload: dict[str, object] = {
        "system": _system_payload(system, cpu),
        "groups": _group_items(groups),
    }
    return _dumps(payload, found, measured)


def build_project_json(
    projects: list[ProcessGroup],
    unknown: ProcessGroup | None,
    system: SystemMemory,
    cpu: SystemCpu,
    found: Churn | None = None,
    measured: bool = False,
) -> str:
    """PJ 別の集約結果を機械可読な JSON 文字列にする。

    Args:
        projects: PJ 別のグループ一覧。
        unknown: PJ が分からなかったプロセスの合計。無ければ None。
        system: システムのメモリ状況。
        cpu: システムの CPU 状況。
        found: 短命プロセスの集計。数えられなかった・数えていなければ None。
        measured: 数えようとしたか。False なら `churn` を出さない。

    Returns:
        整形済み JSON 文字列(`system` と `projects[]` と `unknown`)。
    """
    payload: dict[str, object] = {
        "system": _system_payload(system, cpu),
        "projects": _group_items(projects),
        "unknown": (
            {"total_mb": unknown.total_mb, "total_cpu": unknown.total_cpu, "count": unknown.count}
            if unknown
            else None
        ),
    }
    return _dumps(payload, found, measured)
