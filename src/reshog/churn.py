"""短命プロセスを、それを生んだ「数え始めから動いていた親」へ寄せる純粋関数群。

フックの bash → python のように間の親も短命なことが多い。すぐ上の親で束ねると
「bash が bash を生んだ」としか分からないので、数え始めの時点で動いていた祖先
(claude のセッション・pytest・CI のランナー等)まで辿って束ねる。
"""

from collections.abc import Iterable

from .constants import (
    CHURN_MAX_DEPTH,
    CHURN_UNKNOWN_PARENT,
    DEFUNCT,
    ENV_COMMAND,
    ENV_SPLIT_FLAG,
    ENV_VALUE_FLAGS,
    SCRIPT_SHELLS,
    SHELL_VALUE_FLAGS,
)
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
    shots = list(samples)
    alive = shots[-1] if shots else base
    seen: dict[int, PsEntry] = {}
    for sample in shots:
        for pid, entry in sample.items():
            if pid not in base and pid not in seen:
                seen[pid] = entry

    found: dict[int, list[str]] = {}
    for entry in seen.values():
        source = _source_of(entry, base, seen, alive)
        if source == self_pid:
            continue
        found.setdefault(source, []).append(child_name(entry.command))
    return found


def _source_of(
    entry: PsEntry,
    base: dict[int, PsEntry],
    seen: dict[int, PsEntry],
    alive: dict[int, PsEntry],
) -> int:
    """親を辿り、数え始めから終わりまで動いていた最初の祖先の PID を返す。

    数え始めに写った親も短命なことがある(フックの bash がたまたま写る等)。そこで止めると
    起動元が PID の違う bash に 1 本ずつ割れるので、最後のサンプルに居なければさらに上へ辿る。

    Args:
        entry: 新しく現れたプロセス。
        base: 数え始めのスナップショット。
        seen: 新しく現れたプロセス(間の親を辿るため)。
        alive: 最後のサンプル(終わりまで動いていたかの判定)。

    Returns:
        起動元の PID。辿れなければ CHURN_UNKNOWN_PARENT。
    """
    parent = entry.ppid
    for _ in range(CHURN_MAX_DEPTH):
        if parent in base and parent in alive:
            return parent
        between = base.get(parent) or seen.get(parent)
        if between is None:
            return CHURN_UNKNOWN_PARENT
        parent = between.ppid
    return CHURN_UNKNOWN_PARENT


def child_name(command: str) -> str:
    """生まれたプロセスの表示名。

    名前を読む前に終わったものは ps が `(bash)` のように括弧付きで出すので外す。
    親がまだ回収していない終わったプロセス(ゾンビ)は `<defunct>` と出るので言い換える。
    それ以外はアプリ名の導出(`--group` と同じ規則)に任せる。

    Args:
        command: ps のフルコマンド。

    Returns:
        表示名。分からなければ "?"。
    """
    stripped = command.strip()
    if stripped == DEFUNCT:
        return "(終了済み)"
    if stripped.startswith("(") and stripped.endswith(")"):
        return stripped[1:-1] or "?"
    return _script_name(stripped.split()) if stripped else "?"


def _script_name(argv: list[str]) -> str:
    """シェルと env を素通りして、中で動かしているものの名前を出す。

    pyenv の shim は `bash …/pyenv-exec`・`/usr/bin/env bash …/pyenv` の形で動く。器の名前で
    出すと「bash×197, env×42」になり、原因(pyenv)が表から隠れる。

    Args:
        argv: 空白で割ったコマンド(空でない)。

    Returns:
        表示名。
    """
    base = argv[0].rsplit("/", 1)[-1].lstrip("-")
    if base == ENV_COMMAND:
        inner = _env_command(argv[1:])
        return _script_name(inner) if inner else base
    if base in SCRIPT_SHELLS:
        return _shell_script(base, argv[1:])
    return app_label(" ".join(argv))


def _env_command(args: list[str]) -> list[str]:
    """env の後ろから、実際に動かすコマンドを取り出す(無ければ空)。

    フラグ・`VAR=値`・値を取るフラグ(`-u VAR` 等)の値を飛ばす。`-S` の後ろは
    1 つの文字列を割ったコマンドなので、そこから読み直す。
    """
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == ENV_SPLIT_FLAG:
            return [a.strip("'\"") for a in args[i + 1 :]]
        if arg in ENV_VALUE_FLAGS:
            i += 2
            continue
        if arg.startswith("-") or ("=" in arg and not arg.startswith(("/", "."))):
            i += 1
            continue
        return args[i:]
    return []


def _shell_script(base: str, args: list[str]) -> str:
    """シェルが動かしているスクリプトの名前。コードを直に渡す形(`-c`・`-lc`)は `<シェル> -c`。"""
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in SHELL_VALUE_FLAGS:
            i += 2
            continue
        if arg.startswith("-") and not arg.startswith("--") and "c" in arg[1:]:
            return f"{base} -c"
        if arg.startswith(("-", "+")):
            i += 1
            continue
        return arg.rsplit("/", 1)[-1]
    return base
