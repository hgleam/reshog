"""top / memory_pressure などのテキスト出力を解析する純粋関数群。

外部コマンドを叩かないため単体テストが容易。書式変更への耐性はここで担保する。
"""

import re

from .models import PsEntry

_MEM_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)([GMKB]?)$")
_UNIT_TO_MB: dict[str, float] = {
    "G": 1024.0,
    "M": 1.0,
    "K": 1.0 / 1024,
    "B": 1.0 / (1024 * 1024),
    "": 1.0,
}


def parse_mem_to_mb(value: str) -> float:
    """top の MEM 文字列を MB(float)に変換する。

    末尾の増減記号(+/-, 前サンプルからの変化)は無視する。

    Args:
        value: "32G" / "6759M" / "745K" / "512B" / "745" / "32G+" 等。

    Returns:
        MB 単位の値。

    Raises:
        ValueError: 解釈できない文字列のとき。
    """
    v = value.strip().rstrip("+-")
    m = _MEM_RE.match(v)
    if not m:
        raise ValueError(f"unparseable mem value: {value!r}")
    return float(m.group(1)) * _UNIT_TO_MB[m.group(2)]


def parse_top_processes(output: str) -> list[tuple[int, float, float]]:
    """`top -l 2 -stats pid,mem,cpu` の出力を解析する(**最後のサンプルだけ**)。

    top は 1 サンプル目の %CPU を必ず 0.0 で返すため、collect は 2 サンプル取る。
    出力にはプロセス表が 2 つ入っているので、**新しいほう(最後の表)だけ**を採用する。
    継ぎ足すと同じ PID が 2 回現れ、件数も合計も倍になる。

    Args:
        output: top コマンドの標準出力全体(サンプルが複数含まれてよい)。

    Returns:
        (pid, mem_mb, cpu) のタプルのリスト。top の並びを保つ。
    """
    rows: list[tuple[int, float, float]] = []
    in_table = False
    for line in output.splitlines():
        if line.startswith("PID"):
            # 新しいサンプルの表が始まった。前の表の行は捨てる。
            in_table = True
            rows = []
            continue
        if not in_table:
            continue
        parts = line.split()
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        pid = int(parts[0])
        try:
            mem_mb = parse_mem_to_mb(parts[1])
        except ValueError:
            continue
        try:
            cpu = float(parts[2])
        except ValueError:
            cpu = 0.0
        rows.append((pid, mem_mb, cpu))
    return rows


def _last_header_value(output: str, prefix: str) -> str | None:
    """ヘッダ行の値を返す(複数サンプルがあれば最後のものを採る)。

    Args:
        output: top コマンドの標準出力全体。
        prefix: 行頭に一致させる見出し(例 "PhysMem:")。

    Returns:
        見出し以降の文字列。見つからなければ None。
    """
    found: str | None = None
    for line in output.splitlines():
        if line.startswith(prefix):
            found = line.split(":", 1)[1].strip()
    return found


def parse_load_average(output: str) -> str | None:
    """top のヘッダから Load Avg の値を取り出す。

    Args:
        output: top コマンドの標準出力全体。

    Returns:
        "8.42, 11.53, 15.80" のような文字列。見つからなければ None。

    Note:
        1 / 5 / 15 分平均。**瞬間値ではなく、この 3 つを並べて見る**ことに意味がある。
        1 分だけ高いなら一過性、3 つとも高いなら定常的に詰まっている。
    """
    return _last_header_value(output, "Load Avg:")


def parse_cpu_usage(output: str) -> str | None:
    """top のヘッダから CPU usage の内訳を取り出す。

    Args:
        output: top コマンドの標準出力全体。

    Returns:
        "19.97% user, 32.1% sys, 48.1% idle" のような文字列。見つからなければ None。

    Note:
        sys が user を大きく上回るときは、個々のプロセスの計算ではなく
        **カーネル側の処理**(プロセス生成の嵐・I/O・ページング)を疑う手がかりになる。
    """
    return _last_header_value(output, "CPU usage:")


def parse_phys_mem(output: str) -> str | None:
    """top の出力ヘッダから PhysMem 行の内容を取り出す。

    Args:
        output: top コマンドの標準出力全体。

    Returns:
        "PhysMem: " 以降の文字列。見つからなければ None。

    Note:
        出力に複数サンプルが含まれる場合は**最後の値**を返す(最新の状態)。
    """
    return _last_header_value(output, "PhysMem:")


def parse_free_percentage(output: str) -> str | None:
    """memory_pressure の出力から空き割合を取り出す。

    Args:
        output: memory_pressure コマンドの標準出力。

    Returns:
        "37%" 等の文字列。見つからなければ None。
    """
    for line in output.splitlines():
        if "free percentage" in line:
            return line.split(":", 1)[1].strip()
    return None


def parse_ps_snapshot(output: str) -> dict[int, PsEntry]:
    """`ps -Ao pid=,ppid=,rss=,command=` の出力を PID 引きの辞書にする。

    command には空白が含まれるため、先頭 3 列だけを分割してから残りをコマンドとみなす。

    Args:
        output: ps コマンドの標準出力全体。

    Returns:
        pid -> PsEntry の辞書。解釈できない行は捨てる。command が空の行(権限不足・
        ゾンビ)は command="" として残す(プロセス数の母数から落とさないため)。
    """
    entries: dict[int, PsEntry] = {}
    for line in output.splitlines():
        parts = line.split(maxsplit=3)
        # 権限不足・ゾンビでは command が空になる。捨てるとプロセス数を過小に数え、
        # top の走査幅(= len(snapshot) + 余裕)が実プロセス数に届かなくなる。
        if len(parts) == 3:
            parts.append("")
        if len(parts) < 4:
            continue
        pid, ppid, rss_kb, command = parts
        if not (pid.isdigit() and ppid.isdigit() and rss_kb.isdigit()):
            continue
        entries[int(pid)] = PsEntry(
            pid=int(pid),
            ppid=int(ppid),
            rss_mb=int(rss_kb) // 1024,
            command=command.strip(),
        )
    return entries


def parse_lsof_cwd(output: str) -> dict[int, str]:
    """`lsof -a -d cwd -p <pids> -Fpn` の出力を PID -> 作業ディレクトリにする。

    -F 形式は 1 行 1 項目で、先頭 1 文字が種別(p=PID / f=fd / n=パス)。パスは
    行の残り全部なので空白を含んでもそのまま取れる。

    Args:
        output: lsof の標準出力全体。

    Returns:
        pid -> 作業ディレクトリ。読めなかった PID は含まない。
    """
    cwds: dict[int, str] = {}
    pid: int | None = None
    for line in output.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            cwds[pid] = line[1:]
    return cwds


def parse_launchctl_list(output: str) -> dict[int, str]:
    """`launchctl list` の出力を、動いているジョブの PID -> ラベルにする。

    Args:
        output: launchctl list の標準出力全体(PID / Status / Label のタブ区切り)。

    Returns:
        pid -> ラベル。止まっているジョブ(PID が "-")と見出し行は含まない。
    """
    labels: dict[int, str] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].isdigit():
            labels[int(parts[0])] = parts[2]
    return labels


def parse_etime_seconds(value: str) -> int | None:
    """ps の etime(`[[dd-]hh:]mm:ss`)を秒にする。

    Args:
        value: etime の値("21:20:22" / "3-01:02:03" 等)。

    Returns:
        経過秒数。解釈できなければ None。
    """
    days_part, _, clock = value.strip().rpartition("-")
    fields = clock.split(":")
    if not 2 <= len(fields) <= 3 or not all(f.isdigit() for f in fields):
        return None
    if days_part and not days_part.isdigit():
        return None
    seconds = 0
    for field in fields:
        seconds = seconds * 60 + int(field)
    return seconds + int(days_part or 0) * 86400


def parse_ps_etime(output: str) -> dict[int, int]:
    """`ps -o pid=,etime=` の出力を PID -> 経過秒数にする。

    Args:
        output: ps の標準出力全体。

    Returns:
        pid -> 経過秒数。解釈できない行は捨てる。
    """
    elapsed: dict[int, int] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        seconds = parse_etime_seconds(parts[1])
        if seconds is not None:
            elapsed[int(parts[0])] = seconds
    return elapsed
