"""collect と parse を組み合わせ、プロセス一覧とシステム状況を構築する。"""

from dataclasses import replace
from datetime import datetime, timedelta

from . import collect, group, origin, parse
from .models import Process, ProcessGroup, PsEntry, SystemCpu, SystemMemory

# --group は「分散して埋もれているアプリ」を探すのが目的なので、全プロセスを走査する。
# 走査幅は ps の実プロセス数から決める(固定上限にすると、超えた分が黙って合計から落ちる)。
# 実測: このマシンで 1065 プロセス。上限 500 では合計の半分が消えていた。
GROUP_SAMPLE_MIN = 100
# ps を撮ってから top を撮るまでに増えたプロセスのぶんの余裕。
GROUP_SAMPLE_MARGIN = 50


def build_processes(
    count: int, pattern: str | None = None, order: str = "mem"
) -> tuple[list[Process], str]:
    """メモリ上位プロセスを取得し、必要ならコマンド名でフィルタする。

    フィルタ時は取り漏らしを防ぐため多めに top を取得してから絞り込む。

    Args:
        count: 返す最大件数。
        pattern: フルコマンドに対する部分一致(大文字小文字無視)。None なら全件対象。
        order: 並べる基準。"mem"(物理フットプリント)または "cpu"(CPU 使用率)。
            **top 側の並び順ごと切り替える**。取得後に並べ替えるだけでは、
            母集団が「メモリ上位 N 件」のままになり CPU 上位が入らない。

    Returns:
        (Process のリスト, top の生出力) のタプル。生出力はシステム状況の構築に再利用する。
    """
    sample_count = count * 4 if pattern else count
    if sample_count < 40:
        sample_count = 40 if pattern else count
    raw = collect.top_sample(sample_count, order)

    needle = pattern.lower() if pattern else None
    result: list[Process] = []
    for pid, mem_mb, cpu in parse.parse_top_processes(raw):
        command = collect.ps_command(pid)
        if not command:
            continue
        if needle is not None and needle not in command.lower():
            continue
        result.append(
            Process(
                pid=pid,
                mem_mb=round(mem_mb),
                rss_mb=collect.ps_rss_mb(pid),
                cpu=cpu,
                command=command,
            )
        )
        if len(result) >= count:
            break
    return _annotate(result), raw


def build_system_memory(top_raw: str) -> SystemMemory:
    """システム全体のメモリ状況を構築する。

    Args:
        top_raw: build_processes が返した top の生出力(PhysMem 行を含む)。

    Returns:
        SystemMemory。
    """
    return SystemMemory(
        phys=parse.parse_phys_mem(top_raw),
        swap=collect.swap_usage() or None,
        free_percentage=parse.parse_free_percentage(collect.memory_pressure()),
    )


def build_system_cpu(top_raw: str) -> SystemCpu:
    """システム全体の CPU 状況を構築する。

    Args:
        top_raw: build_processes が返した top の生出力(ヘッダを含む)。

    Returns:
        SystemCpu。
    """
    return SystemCpu(
        load_average=parse.parse_load_average(top_raw),
        usage=parse.parse_cpu_usage(top_raw),
    )


def build_groups(
    count: int, pattern: str | None = None, order: str = "mem"
) -> tuple[list[ProcessGroup], str]:
    """アプリ単位に集約したメモリ使用量の上位を返す。

    プロセス単位のランキングでは、ヘルパープロセスへ分散するアプリ(Chromium 系等)が
    順位に現れない。全プロセスを走査して親子関係で畳んでから順位を付ける。

    Args:
        count: 返すグループの最大数。
        pattern: フルコマンドに対する部分一致(大文字小文字無視)。None なら全件対象。

    Returns:
        (ProcessGroup のリスト, top の生出力) のタプル。

    Note:
        フィルタは集約前のプロセスに掛かる。一致したプロセスだけが合計に入る。
        top の走査幅は ps の実プロセス数から決める(固定上限で切ると、あふれた分が
        黙って合計から抜け、「分散して埋もれている合計」という目的が崩れる)。
    """
    processes, snapshot, raw = _scan_all(pattern, order)
    return group.group_processes(processes, snapshot, order)[:count], raw


def build_projects(
    count: int, pattern: str | None = None, order: str = "mem"
) -> tuple[list[ProcessGroup], ProcessGroup | None, str]:
    """PJ 別(作業ディレクトリの git リポ / launchd ジョブ)に合計した上位を返す。

    判定は PJ 列と同じ(`origin.resolve`)。PJ が分からないプロセスは順位に混ぜず、
    別に合計して返す(GUI アプリがまとめて 1 位に居座り、PJ どうしの比較が見えなくなるため)。

    Args:
        count: 返す PJ の最大数。
        pattern: フルコマンドに対する部分一致(大文字小文字無視)。合計の前に掛かる。
        order: 並べる基準。"mem" または "cpu"。

    Returns:
        (PJ 別の ProcessGroup のリスト, PJ 不明の合計(無ければ None), top の生出力)。
    """
    processes, _, raw = _scan_all(pattern, order)
    processes = _with_origins(processes)
    known = [p for p in processes if p.origin is not None]
    unknown = [p for p in processes if p.origin is None]
    projects = group.bucket_processes(
        known, lambda p: origin.label(p.origin) if p.origin else "-", order
    )
    unknown_total = group.bucket_processes(unknown, lambda p: "-", order)
    return projects[:count], (unknown_total[0] if unknown_total else None), raw


def _scan_all(
    pattern: str | None, order: str
) -> tuple[list[Process], dict[int, PsEntry], str]:
    """全プロセスを走査する(--group / --project の母集団)。

    Args:
        pattern: フルコマンドに対する部分一致(大文字小文字無視)。None なら全件対象。
        order: top の並び順。

    Returns:
        (Process のリスト, ps のスナップショット, top の生出力)。
    """
    snapshot = parse.parse_ps_snapshot(collect.ps_snapshot())
    raw = collect.top_sample(
        max(len(snapshot) + GROUP_SAMPLE_MARGIN, GROUP_SAMPLE_MIN), order
    )

    needle = pattern.lower() if pattern else None
    processes: list[Process] = []
    for pid, mem_mb, cpu in parse.parse_top_processes(raw):
        entry = snapshot.get(pid)
        if entry is None or not entry.command:
            continue
        if needle is not None and needle not in entry.command.lower():
            continue
        processes.append(
            Process(
                pid=pid,
                mem_mb=round(mem_mb),
                rss_mb=entry.rss_mb,
                cpu=cpu,
                command=entry.command,
            )
        )
    return processes, snapshot, raw


def build_app_processes(
    label: str, count: int, order: str = "mem"
) -> tuple[list[Process], str]:
    """指定アプリに属するプロセスだけを、メモリ降順で返す(--group のドリルダウン)。

    所属判定は `--group` と同じ親子関係(`group.group_label`)で行う。コマンド文字列への
    部分一致(`-g`)では、実行ファイル名が親アプリ名を含まない子プロセス(MCP サーバ等)を
    取りこぼすため、同じ集約規則を使う。

    Args:
        label: アプリ名(--group の APP 列の値。大文字小文字は無視する)。
        count: 返す最大件数。

    Returns:
        (Process のリスト, top の生出力) のタプル。
    """
    snapshot = parse.parse_ps_snapshot(collect.ps_snapshot())
    raw = collect.top_sample(
        max(len(snapshot) + GROUP_SAMPLE_MARGIN, GROUP_SAMPLE_MIN), order
    )

    needle = label.lower()
    result: list[Process] = []
    for pid, mem_mb, cpu in parse.parse_top_processes(raw):
        entry = snapshot.get(pid)
        if entry is None or not entry.command:
            continue
        if group.group_label(pid, snapshot).lower() != needle:
            continue
        result.append(
            Process(
                pid=pid,
                mem_mb=round(mem_mb),
                rss_mb=entry.rss_mb,
                cpu=cpu,
                command=entry.command,
            )
        )
        if len(result) >= count:
            break
    return _annotate(result), raw


def _annotate(processes: list[Process]) -> list[Process]:
    """表示するプロセスに由来(PJ)と開始時刻を付ける。

    外部コマンドは表示する分だけを対象に、それぞれ 1 回ずつしか叩かない
    (PID ごとに叩くと表示件数に比例して遅くなる)。

    Args:
        processes: 表示するプロセス。

    Returns:
        origin / started_at を埋めたプロセス(順序は保つ)。
    """
    if not processes:
        return processes
    elapsed = parse.parse_ps_etime(collect.process_elapsed([p.pid for p in processes]))
    now = _now()
    return [
        replace(
            p,
            started_at=(
                now - timedelta(seconds=elapsed[p.pid]) if p.pid in elapsed else None
            ),
        )
        for p in _with_origins(processes)
    ]


def _with_origins(processes: list[Process]) -> list[Process]:
    """プロセスに由来(PJ)を付ける。lsof / launchctl は対象の数によらず 1 回ずつ。

    Args:
        processes: 対象プロセス。

    Returns:
        origin を埋めたプロセス(順序は保つ)。
    """
    if not processes:
        return processes
    cwds = parse.parse_lsof_cwd(collect.process_cwds([p.pid for p in processes]))
    labels = parse.parse_launchctl_list(collect.launchd_jobs())
    return [
        replace(p, origin=origin.resolve(cwds.get(p.pid), labels.get(p.pid)))
        for p in processes
    ]


def _now() -> datetime:
    """開始時刻の基準にする現在時刻(テストで差し替える)。"""
    return datetime.now().replace(microsecond=0)
