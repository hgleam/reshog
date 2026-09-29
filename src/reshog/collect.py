"""macOS の外部コマンド(top / ps / lsof / launchctl / sysctl / memory_pressure)で状況を読む I/O 層。

外部コマンドを叩くのはこのモジュールに限定し、解析ロジック(parse.py)から分離する。
読むだけで何も変えない。プロセスを止める副作用は control.py に置く。
"""

import os
import subprocess

from .constants import TOP_SAMPLES


def _run(args: list[str]) -> str:
    """コマンドを実行し標準出力を返す(失敗時は空文字)。

    Args:
        args: コマンドと引数のリスト。

    Returns:
        標準出力。コマンドが見つからない/失敗しても例外は投げず空文字を返す。
    """
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=False)
    except (OSError, ValueError):
        return ""
    return proc.stdout


def top_sample(count: int, order: str = "mem") -> str:
    """上位 count 件を含む top の出力を返す(2 サンプル分)。

    Args:
        count: 取得件数。
        order: top の並び順("mem" または "cpu")。**呼び出し側が見たい順で指定する**。
            表示側で並べ替えるだけでは、top が返した上位 N の中でしか順位が付かず、
            母集団が「メモリ上位 N 件」に固定されてしまう(CPU 上位が入っていない)。

    Returns:
        top の標準出力全体(2 サンプル分。ヘッダを含む)。
    """
    return _run(
        [
            "top",
            "-l",
            str(TOP_SAMPLES),
            "-o",
            order,
            "-n",
            str(count),
            "-stats",
            "pid,mem,cpu",
        ]
    )


def ps_command(pid: int) -> str:
    """PID のフルコマンド文字列を返す。

    Args:
        pid: プロセス ID。

    Returns:
        フルコマンド。取得できなければ空文字。
    """
    return _run(["ps", "-o", "command=", "-p", str(pid)]).strip()


def ps_rss_mb(pid: int) -> int:
    """PID の ps RSS を MB で返す。

    Args:
        pid: プロセス ID。

    Returns:
        RSS(MB)。取得できなければ 0。
    """
    out = _run(["ps", "-o", "rss=", "-p", str(pid)]).strip()
    return int(out) // 1024 if out.isdigit() else 0


def ps_snapshot() -> str:
    """全プロセスの pid / ppid / rss / command を 1 回の ps で返す。

    --group は数百プロセスを対象にするため、PID ごとに ps を叩くと呼び出しが
    プロセス数の 2 倍に膨らむ。一括取得に置き換える。

    Returns:
        `ps -Ao pid=,ppid=,rss=,command=` の標準出力。取得できなければ空文字。
    """
    return _run(["ps", "-Ao", "pid=,ppid=,rss=,command="])


def process_cwds(pids: list[int]) -> str:
    """PID 群の作業ディレクトリを 1 回の lsof で返す。

    PID ごとに叩くと表示件数に比例して遅くなるため、カンマ区切りでまとめて渡す。
    読めない PID(root のプロセス等)は出力に現れない。

    Args:
        pids: 対象 PID。空なら何も実行しない(-p を空で渡すと全プロセスを列挙するため)。

    Returns:
        `lsof -a -d cwd -p <pids> -Fpn` の標準出力。取得できなければ空文字。
    """
    if not pids:
        return ""
    return _run(["lsof", "-a", "-d", "cwd", "-p", ",".join(map(str, pids)), "-Fpn"])


def process_elapsed(pids: list[int]) -> str:
    """PID 群の経過時間を 1 回の ps で返す。

    開始時刻そのもの(lstart)は曜日・月名がロケールで変わるため、数字だけの etime を取る。

    Args:
        pids: 対象 PID。空なら何も実行しない(-p を空で渡すと ps がエラーになるため)。

    Returns:
        `ps -o pid=,etime= -p <pids>` の標準出力。取得できなければ空文字。
    """
    if not pids:
        return ""
    return _run(["ps", "-o", "pid=,etime=", "-p", ",".join(map(str, pids))])


def launchd_domain() -> str:
    """launchd_jobs が読むドメイン。root なら system、それ以外はそのユーザーの gui。

    `launchctl list` は叩いた権限のドメインを返す。止める案内のドメインもこれに合わせる。

    Returns:
        "system" または "gui/<uid>"。
    """
    uid = os.geteuid()
    return "system" if uid == 0 else f"gui/{uid}"


def launchd_jobs() -> str:
    """ログインユーザーの launchd ジョブ一覧を返す。

    Returns:
        `launchctl list` の標準出力。取得できなければ空文字。
    """
    return _run(["launchctl", "list"])


def swap_usage() -> str:
    """sysctl vm.swapusage の値を返す。

    Returns:
        スワップ使用状況の文字列。取得できなければ空文字。
    """
    return _run(["sysctl", "-n", "vm.swapusage"]).strip()


def memory_pressure() -> str:
    """memory_pressure の出力を返す。

    Returns:
        標準出力全体。取得できなければ空文字。
    """
    return _run(["memory_pressure"])
