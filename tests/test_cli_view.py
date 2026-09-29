"""表示の組み立て(cli._render_view)のテスト。"""

import pytest

from reshog import cli, render, report
from reshog.models import ProcessGroup, SystemCpu, SystemMemory


class _SpyConsole:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def clear(self) -> None:
        self.events.append("clear")

    def print(self, *args: object, **kwargs: object) -> None:
        pass


@pytest.mark.parametrize("view", ["processes", "app", "group", "project"])
def test_watch_clears_only_after_the_data_is_ready(
    monkeypatch: pytest.MonkeyPatch, view: str
) -> None:
    """--watch は集め終えてから画面を消す。

    全プロセスの走査は数十秒かかる。先に消すと、その間ずっと画面が空になる
    (#16 の --project --watch がそうなっていた)。
    """
    events: list[str] = []
    monkeypatch.setattr(
        report, "build_processes", lambda *a: (events.append("build") or [], "")
    )
    monkeypatch.setattr(
        report, "build_app_processes", lambda *a: (events.append("build") or [], "")
    )
    monkeypatch.setattr(report, "build_groups", lambda *a: (events.append("build") or [], ""))
    monkeypatch.setattr(
        report, "build_projects", lambda *a: (events.append("build") or [], None, "")
    )
    monkeypatch.setattr(report, "build_system_memory", lambda raw: SystemMemory(None, None, None))
    monkeypatch.setattr(report, "build_system_cpu", lambda raw: SystemCpu(None, None))
    for name in ("render_table", "render_group_table", "render_project_table"):
        monkeypatch.setattr(render, name, lambda *a, **k: events.append("render"))

    cli._render_view(_SpyConsole(events), view, 5, None, "mem", "x", clear=True)  # type: ignore[arg-type]
    assert events == ["build", "clear", "render"]


def test_aggregate_views_offer_nothing_to_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    group = ProcessGroup(label="a", members=())
    monkeypatch.setattr(report, "build_groups", lambda *a: ([group], ""))
    monkeypatch.setattr(report, "build_system_memory", lambda raw: SystemMemory(None, None, None))
    monkeypatch.setattr(report, "build_system_cpu", lambda raw: SystemCpu(None, None))
    monkeypatch.setattr(render, "render_group_table", lambda *a, **k: None)
    assert cli._render_view(_SpyConsole([]), "group", 5, None, "mem", None) == []
