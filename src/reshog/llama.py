"""llama-server(ローカル LLM)の休止状態を判定する。

`--sleep-idle-seconds` の休止は、同じプロセスのままモデルをメモリから外すだけ。
プロセスの開始時刻(「起動」列)は変わらないので、いまモデルを掴んでいるか・いつからかを別に出す。
"""

import shlex
from datetime import timedelta

from .constants import (
    LLAMA_DEFAULT_PORT,
    LLAMA_EXECUTABLE,
    LLAMA_LOCAL_HOSTS,
    LLAMA_LOG_TIME_RE,
    LLAMA_SLEEP_ENTER,
    LLAMA_SLEEP_EXIT,
)


def endpoint(command: str) -> tuple[str, int] | None:
    """llama-server なら、問い合わせる先(ホスト, ポート)を返す。

    自分のマシンで待ち受けているものだけ。他のマシンへは問い合わせない。

    Args:
        command: フルコマンド文字列。

    Returns:
        (ホスト, ポート)。llama-server でない・他のマシンなら None。
    """
    try:
        args = shlex.split(command)
    except ValueError:
        return None
    if not args or args[0].rsplit("/", 1)[-1] != LLAMA_EXECUTABLE:
        return None
    host, port = "127.0.0.1", LLAMA_DEFAULT_PORT
    for i, arg in enumerate(args):
        name, eq, inline = arg.partition("=")
        value = inline if eq else (args[i + 1] if i + 1 < len(args) else "")
        if name == "--host":
            host = value
        elif name == "--port" and value.isdigit():
            port = int(value)
    if host not in LLAMA_LOCAL_HOSTS:
        return None
    return "127.0.0.1", port


def last_transition(log_text: str) -> tuple[bool, timedelta] | None:
    """ログの末尾から、今回の起動で最後に休止へ出入りした行を探す。

    行頭の時刻は起動からの `分.秒.ミリ秒.マイクロ秒`。起動し直すと 0 に戻り、同じファイルに
    続けて書かれるので、時刻が戻ったところより後(= 今回の起動)だけを見る。

    Args:
        log_text: ログの末尾。

    Returns:
        (休止に入ったなら True, 起動からの経過)。今回の起動に出入りが無ければ None。
    """
    found: tuple[bool, timedelta] | None = None
    previous: timedelta | None = None
    for line in log_text.splitlines():
        match = LLAMA_LOG_TIME_RE.match(line)
        if match is None:
            continue
        minutes, seconds, millis, _micros = (int(g) for g in match.groups())
        offset = timedelta(minutes=minutes, seconds=seconds, milliseconds=millis)
        if previous is not None and offset < previous:
            found = None  # 起動し直した。前の起動の出入りは今のプロセスのものではない
        previous = offset
        if LLAMA_SLEEP_ENTER in line:
            found = (True, timedelta(minutes=minutes, seconds=seconds))
        elif LLAMA_SLEEP_EXIT in line:
            found = (False, timedelta(minutes=minutes, seconds=seconds))
    return found
