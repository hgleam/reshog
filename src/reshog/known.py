"""上位に出る macOS のプロセスに「何のためのものか・止めてよいか」を添える。

対応表は constants.KNOWN_PROCESSES。ここは実行ファイル名で引くだけ。
"""

from .constants import KNOWN_PROCESS_DIRS, KNOWN_PROCESSES
from .models import KnownProcess


def describe(command: str) -> KnownProcess | None:
    """フルコマンドから、既知の OS のプロセスの説明を返す。

    実行ファイル名(最初の語のパスの最後)で完全一致させ、置き場所も OS の場所に限る。
    部分一致や名前だけの一致にすると、`python WindowServer.py` や `/tmp/mds` のような
    別物を OS のプロセスとして説明してしまう。

    Args:
        command: フルコマンド文字列。

    Returns:
        説明。既知でなければ None。
    """
    path = command.split(" ", 1)[0]
    if not path.startswith(KNOWN_PROCESS_DIRS):
        return None
    entry = KNOWN_PROCESSES.get(path.rsplit("/", 1)[-1])
    if entry is None:
        return None
    purpose, advice, stoppable = entry
    return KnownProcess(purpose=purpose, advice=advice, stoppable=stoppable)
