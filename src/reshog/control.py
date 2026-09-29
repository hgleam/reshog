"""プロセスを止める(取り消せない副作用をここに閉じる)。

状況を読む collect.py とは別に置く。読む側は何度呼んでも害が無いが、こちらは 1 回で
プロセスが消える。同じファイルにあると、読む関数を足すついでに触れる距離に来る。
"""

import os
import signal
from typing import Literal


def current_pid() -> int:
    """reshog 自身の PID を返す。

    Returns:
        自プロセスの PID。
    """
    return os.getpid()


def send_signal(pid: int, sig: signal.Signals) -> Literal["ok", "not_found", "denied"]:
    """PID にシグナルを送る(プロセス停止の副作用をこの I/O 層に閉じる)。

    os.kill の例外を制御フロー用の結果コードに翻訳し、握り潰さず呼び出し側へ伝える。

    Args:
        pid: 対象プロセス ID。
        sig: 送信するシグナル(SIGTERM / SIGKILL 等)。

    Returns:
        "ok": 送信成功 / "not_found": プロセスが存在しない / "denied": 権限不足。
    """
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return "not_found"
    except PermissionError:
        return "denied"
    return "ok"
