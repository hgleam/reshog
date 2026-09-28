"""プロセスをアプリ単位へ集約する純粋関数群。

Chromium 系ブラウザや MCP サーバはヘルパープロセスへ分散するため、1 プロセスずつの
ランキングでは順位に現れない(実測: ixBrowser が 122 プロセスに割れて 15.5GB)。
親子関係をたどってアプリ単位へ畳み、その分散を可視化する。
"""

from collections.abc import Callable

from .models import Process, ProcessGroup, PsEntry

# argv[0] がこれらのときは「何を動かしているか」(スクリプト名)を表示名に採る。
_INTERPRETERS = frozenset(
    {
        "node",
        "python",
        "python3",
        "Python",
        "ruby",
        "perl",
        "php",
        "deno",
        "bun",
        "java",
        "Rscript",
    }
)

# 親としてたどっても意味を持たない「器」。ここで止めるとシェルや端末に全部吸われる。
_TRANSPARENT = frozenset(
    {
        "tmux",
        "tmux-server",
        "screen",
        "login",
        "sh",
        "bash",
        "zsh",
        "fish",
        "env",
        "xargs",
        "sshd",
        "launchd",
        "Terminal",
        "iTerm2",
        "Alacritty",
        "WezTerm",
        "kitty",
        "Ghostty",
    }
)


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
    if bundle is not None and bundle not in _INTERPRETERS:
        return bundle

    argv = command.split()
    if not argv:
        return "?"
    # ログインシェルは argv[0] が "-zsh" のように - 始まりで現れる。
    base = argv[0].rsplit("/", 1)[-1].lstrip("-")
    if not base:
        return "?"
    if base in _INTERPRETERS or bundle in _INTERPRETERS:
        for arg in argv[1:]:
            if arg.startswith("-"):
                continue
            return arg.rsplit("/", 1)[-1]
    return base


def group_label(pid: int, snapshot: dict[int, PsEntry]) -> str:
    """PID が属するアプリ名を、親をたどって決める。

    最上位の祖先まで遡り、シェル・端末・多重化ツール(_TRANSPARENT)でない最初のものを
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
        if label not in _TRANSPARENT:
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
    return bucket_processes(processes, lambda p: group_label(p.pid, snapshot), order)


def bucket_processes(
    processes: list[Process], key: Callable[[Process], str], order: str = "mem"
) -> list[ProcessGroup]:
    """プロセスを key が返す名前で束ね、指定した資源の合計降順で返す。

    アプリ別(--group)と PJ 別(--project)は束ねるキーだけが違う。並べ方を 2 か所に
    書くと、片方だけ直って順位の付け方がずれるため、ここに 1 つだけ置く。

    Args:
        processes: 集約対象のプロセス(降順である必要はない)。
        key: プロセスから束ねる名前を返す関数。
        order: 並べる基準。"mem"(合計メモリ)または "cpu"(合計 CPU)。

    Returns:
        ProcessGroup のリスト(指定資源の合計降順。同値なら件数の多い順)。
        グループ内の members も同じ基準の降順に並ぶ(最大単体の表示に使うため)。
    """
    by_cpu = order == "cpu"
    buckets: dict[str, list[Process]] = {}
    for process in processes:
        buckets.setdefault(key(process), []).append(process)

    groups = [
        ProcessGroup(
            label=label,
            members=tuple(
                sorted(
                    members,
                    key=(lambda p: p.cpu) if by_cpu else (lambda p: p.mem_mb),
                    reverse=True,
                )
            ),
        )
        for label, members in buckets.items()
    ]
    groups.sort(
        key=(lambda g: (g.total_cpu, g.count)) if by_cpu else (lambda g: (g.total_mb, g.count)),
        reverse=True,
    )
    return groups
