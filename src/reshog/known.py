"""上位に出る macOS のプロセスに「何のためのものか・止めてよいか」を添える。

対応表は constants.KNOWN_PROCESSES。ここは実行ファイル名で引くだけ。
"""

from .constants import KNOWN_PROCESSES
from .models import KnownProcess


def describe(command: str) -> KnownProcess | None:
    """フルコマンドから、既知の OS のプロセスの説明を返す。

    実行ファイル名(最初の語のパスの最後)で完全一致させる。部分一致にすると、
    `python WindowServer.py` のような別物を OS のプロセスとして説明してしまう。

    Args:
        command: フルコマンド文字列。

    Returns:
        説明。既知でなければ None。
    """
    executable = command.split(" ", 1)[0].rsplit("/", 1)[-1]
    entry = KNOWN_PROCESSES.get(executable)
    if entry is None:
        return None
    purpose, advice, stoppable = entry
    return KnownProcess(purpose=purpose, advice=advice, stoppable=stoppable)
