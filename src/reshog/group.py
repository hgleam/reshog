"""プロセスをアプリ単位へ集約する純粋関数群。

Chromium 系ブラウザや MCP サーバはヘルパープロセスへ分散するため、1 プロセスずつの
ランキングでは順位に現れない(実測: ixBrowser が 122 プロセスに割れて 15.5GB)。
親子関係をたどってアプリ単位へ畳み、その分散を可視化する。
"""

from . import aggregate
from .constants import INTERPRETERS, TRANSPARENT
from .models import Process, ProcessGroup, PsEntry


def _bundle_name(command: str) -> str | None:
    """コマンドのパスに含まれる最初の .app バンドル名を返す。

    Args:
        command: フルコマンド文字列。

    Returns:
        "Google Chrome" 等。.app を含まなければ None。
    """
    marker = ".app/"
    index = command.find(marker)
    if index < 0:
        return None
    head = command[:index]
    slash = head.rfind("/")
    return head[slash + 1 :] if slash >= 0 else head


def app_label(command: str) -> str:
    """フルコマンドから表示用のアプリ名を導出する。

    .app バンドル名を最優先する。ただし Python.app のようなインタプリタの入れ物は
    アプリ名にならないため、その場合は実行しているスクリプト名を採る。

    Args:
        command: フルコマンド文字列。

    Returns:
        アプリ名。導出できなければ "?"。
    """
    bundle = _bundle_name(command)
    if bundle is not None and bundle not in INTERPRETERS:
        return bundle

    argv = command.split()
    if not argv:
        return "?"
    # ログインシェルは argv[0] が "-zsh" のように - 始まりで現れる。
    base = argv[0].rsplit("/", 1)[-1].lstrip("-")
    if not base:
        return "?"
    if base in INTERPRETERS or bundle in INTERPRETERS:
        for arg in argv[1:]:
            if arg.startswith("-"):
                continue
            return arg.rsplit("/", 1)[-1]
    return base


def group_label(pid: int, snapshot: dict[int, PsEntry]) -> str:
    """PID が属するアプリ名を、親をたどって決める。

    最上位の祖先まで遡り、シェル・端末・多重化ツール(TRANSPARENT)でない最初のものを
    そのプロセスの所属アプリとみなす。tmux 配下の CLI が全部 tmux に吸われるのを防ぐ。

    Args:
        pid: 対象プロセス ID。
        snapshot: 全プロセスの ps 情報(pid -> PsEntry)。

    Returns:
        アプリ名。snapshot に PID が無ければ "?"。
    """
    entry = snapshot.get(pid)
    if entry is None:
        return "?"

    chain: list[PsEntry] = []
    seen: set[int] = set()
    current: PsEntry | None = entry
    while current is not None and current.pid not in seen:
        seen.add(current.pid)
        chain.append(current)
        if current.ppid in (0, 1):
            break
        current = snapshot.get(current.ppid)

    for ancestor in reversed(chain):
        label = app_label(ancestor.command)
        if label not in TRANSPARENT:
            return label
    return app_label(entry.command)


def group_processes(
    processes: list[Process], snapshot: dict[int, PsEntry], order: str = "mem"
) -> list[ProcessGroup]:
    """プロセス一覧をアプリ単位へ集約し、指定した資源の合計降順で返す。

    Args:
        processes: 集約対象のプロセス(降順である必要はない)。
        snapshot: 全プロセスの ps 情報(親子関係の解決に使う)。
        order: 並べる基準。"mem"(合計メモリ)または "cpu"(合計 CPU)。

    Returns:
        ProcessGroup のリスト(並びは bucket_processes と同じ)。
    """
    return aggregate.bucket_processes(processes, lambda p: group_label(p.pid, snapshot), order)
