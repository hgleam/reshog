"""短命プロセスを、それを生んだ「数え始めから動いていた親」へ寄せる純粋関数群。

フックの bash → python のように間の親も短命なことが多い。すぐ上の親で束ねると
「bash が bash を生んだ」としか分からないので、数え始めの時点で動いていた祖先
(claude のセッション・pytest・CI のランナー等)まで辿って束ねる。
"""

from collections.abc import Iterable

from .constants import CHURN_MAX_DEPTH, CHURN_UNKNOWN_PARENT
from .group import app_label
from .models import PsEntry


def attribute(
    base: dict[int, PsEntry], samples: Iterable[dict[int, PsEntry]], self_pid: int
) -> dict[int, list[str]]:
    """数え始めの後に現れたプロセスを、起動元の PID ごとに名前で集める。

    Args:
        base: 数え始めの ps のスナップショット(ここに居るものは「新しく生まれた」に数えない)。
        samples: その後に撮ったスナップショット(撮った順)。
        self_pid: 数えている自分の PID。自分が叩いた ps は数えない。

    Returns:
        起動元の PID -> 生まれたプロセスの名前(現れた順)。起動元が分からないものは
        CHURN_UNKNOWN_PARENT に入れる(本数から落とさない)。
    """
    seen: dict[int, PsEntry] = {}
    for sample in samples:
        for pid, entry in sample.items():
            if pid not in base and pid not in seen:
                seen[pid] = entry

    found: dict[int, list[str]] = {}
    for entry in seen.values():
        source = _source_of(entry, base, seen)
        if source == self_pid:
            continue
        found.setdefault(source, []).append(child_name(entry.command))
    return found


def _source_of(entry: PsEntry, base: dict[int, PsEntry], seen: dict[int, PsEntry]) -> int:
    """親を辿り、数え始めから動いていた最初の祖先の PID を返す。

    Args:
        entry: 新しく現れたプロセス。
        base: 数え始めのスナップショット。
        seen: 新しく現れたプロセス(間の親を辿るため)。

    Returns:
        起動元の PID。辿れなければ CHURN_UNKNOWN_PARENT。
    """
    parent = entry.ppid
    for _ in range(CHURN_MAX_DEPTH):
        if parent in base:
            return parent
        between = seen.get(parent)
        if between is None:
            return CHURN_UNKNOWN_PARENT
        parent = between.ppid
    return CHURN_UNKNOWN_PARENT


def child_name(command: str) -> str:
    """生まれたプロセスの表示名。

    名前を読む前に終わったものは ps が `(bash)` のように括弧付きで出すので外す。
    それ以外はアプリ名の導出(`--group` と同じ規則)に任せる。

    Args:
        command: ps のフルコマンド。

    Returns:
        表示名。分からなければ "?"。
    """
    stripped = command.strip()
    if stripped.startswith("(") and stripped.endswith(")"):
        return stripped[1:-1] or "?"
    return app_label(stripped) if stripped else "?"
