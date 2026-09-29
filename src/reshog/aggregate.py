"""プロセスを名前で束ねて合計し、順位を付ける。

アプリ別(--group)と PJ 別(--project)は束ねるキーだけが違う同じ集約なので、
合計と並べ方をここに 1 つだけ置く。キーの決め方はそれぞれ group.py / origin.py が持つ。
"""

from collections.abc import Callable

from .models import Process, ProcessGroup


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
