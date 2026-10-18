"""短命プロセス(数秒で生まれて消えるもの)の出どころ集計のテスト。

top の 2 サンプルの間に生まれて終わるプロセスは、CPU 上位の一覧に一度も出ない。
9 本の claude セッションがフックを起動し続け、5 秒で 656 本生まれていたのに、
cpuhog の一覧には WindowServer しか出なかった(2026-10-18)。
"""

import io
from collections.abc import Iterator

import pytest
from rich.console import Console

from reshog import churn, cli, collect, control, render, report
from reshog.constants import CHURN_UNKNOWN_PARENT
from reshog.models import Churn, ChurnSource, Origin, PsEntry, SystemCpu, SystemMemory


def _entry(pid: int, ppid: int, command: str) -> PsEntry:
    return PsEntry(pid=pid, ppid=ppid, rss_mb=0, command=command)


def _snapshot(*entries: PsEntry) -> dict[int, PsEntry]:
    return {e.pid: e for e in entries}


# サンプルを撮り始めた時点で動いていたもの。100 = claude, 200 = pytest, 999 = 自分。
_BASE = _snapshot(
    _entry(1, 0, "/sbin/launchd"),
    _entry(100, 1, "/Users/u/.local/bin/claude"),
    _entry(200, 1, "/u/.venv/bin/python -m pytest -n 4"),
    _entry(999, 1, "/u/.local/bin/cpuhog"),
)


class TestAttribute:
    def test_short_lived_children_are_counted_under_the_parent_that_was_already_running(
        self,
    ) -> None:
        sample = _snapshot(
            *_BASE.values(), _entry(300, 100, "(bash)"), _entry(301, 100, "gh pr view")
        )
        found = churn.attribute(_BASE, [sample], self_pid=999)
        assert found == {100: ["bash", "gh"]}

    def test_grandchildren_are_traced_back_through_parents_that_already_exited(self) -> None:
        """フックの bash → python のように、間の親も短命なら、さらに上の長命な親まで辿る。"""
        first = _snapshot(*_BASE.values(), _entry(300, 100, "bash -c hook.sh"))
        # 300 は次のサンプルでは消えているが、孫の 301 は 300 を親に持つ。
        second = _snapshot(*_BASE.values(), _entry(301, 300, "python3 /h/hooks/guard.py"))
        found = churn.attribute(_BASE, [first, second], self_pid=999)
        assert found == {100: ["bash", "guard.py"]}

    def test_a_process_seen_in_several_samples_is_counted_once(self) -> None:
        sample = _snapshot(*_BASE.values(), _entry(300, 200, "python worker"))
        found = churn.attribute(_BASE, [sample, sample, sample], self_pid=999)
        assert found == {200: ["worker"]}

    def test_our_own_ps_polls_are_not_counted(self) -> None:
        """数えるために叩いた ps 自身を、負荷の原因として出さない。"""
        sample = _snapshot(*_BASE.values(), _entry(300, 999, "ps -Ao pid=,ppid=,rss=,command="))
        assert churn.attribute(_BASE, [sample], self_pid=999) == {}

    def test_parent_unknown_is_kept_under_zero_instead_of_dropped(self) -> None:
        """親がどのサンプルにも写らなかったものも、本数からは落とさない。"""
        sample = _snapshot(*_BASE.values(), _entry(300, 777, "(bash)"))
        assert churn.attribute(_BASE, [sample], self_pid=999) == {CHURN_UNKNOWN_PARENT: ["bash"]}

    def test_processes_already_running_at_the_start_are_not_new(self) -> None:
        assert churn.attribute(_BASE, [_BASE], self_pid=999) == {}


class TestChildName:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("(bash)", "bash"),  # 名前を読む前に終わったもの
            ("/opt/homebrew/bin/gh pr view 1", "gh"),
            ("python3 /h/hooks/guard.py --x", "guard.py"),
            ("", "?"),
        ],
    )
    def test_name(self, command: str, expected: str) -> None:
        assert churn.child_name(command) == expected


class TestModel:
    def test_total_and_rate(self) -> None:
        source = ChurnSource(pid=100, command="claude", origin=None, children=("bash",) * 30)
        found = Churn(seconds=3.0, sources=(source,))
        assert found.total == 30
        assert found.per_second == 10.0

    def test_main_children(self) -> None:
        source = ChurnSource(
            pid=100,
            command="claude",
            origin=None,
            children=("bash", "gh", "bash", "git", "bash", "gh", "ps"),
        )
        assert source.main_children(3) == "bash×3, gh×2, git×1"


class TestBuildChurn:
    @pytest.fixture(autouse=True)
    def _mock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        base = "1 0 1 /sbin/launchd\n100 1 1 /Users/u/.local/bin/claude\n999 1 1 cpuhog\n"
        later = base + "300 100 1 (bash)\n301 100 1 gh pr view\n302 999 1 ps -Ao\n"
        snapshots: Iterator[str] = iter([base, later, later + "303 100 1 (bash)\n"])
        clock = iter([0.0, 1.5, 3.1])  # 撮り始め / 1 回目の後 / 2 回目の後(ここで 3 秒を超える)
        monkeypatch.setattr(collect, "ps_snapshot", lambda: next(snapshots))
        monkeypatch.setattr(report, "_clock", lambda: next(clock))
        monkeypatch.setattr(report, "_sleep", lambda seconds: None)
        monkeypatch.setattr(control, "current_pid", lambda: 999)
        monkeypatch.setattr(collect, "process_cwds", lambda pids: "p100\nn/Users/u/repo\n")
        monkeypatch.setattr(collect, "launchd_jobs", lambda: "")
        monkeypatch.setattr(collect, "launchd_domain", lambda: "gui/501")

    def test_counts_new_processes_by_the_running_parent(self) -> None:
        found = report.build_churn(3.0)
        assert found.total == 3
        assert found.seconds == pytest.approx(3.1)  # 実際に数えた時間で割る
        assert [(s.pid, s.children) for s in found.sources] == [(100, ("bash", "gh", "bash"))]
        assert found.sources[0].command == "/Users/u/.local/bin/claude"


class TestRender:
    def _text(self, found: Churn) -> str:
        buffer = io.StringIO()
        render.render_churn(Console(file=buffer, width=200, no_color=True, highlight=False), found)
        return buffer.getvalue()

    def test_shows_rate_parent_project_and_children(self) -> None:
        source = ChurnSource(
            pid=55470,
            command="/Users/u/.local/bin/claude",
            origin=Origin(kind="git", name="smart-front"),
            children=("bash",) * 20 + ("gh",) * 4,
        )
        text = self._text(Churn(seconds=3.0, sources=(source,)))
        assert "24 本以上" in text
        assert "8 本/秒" in text
        assert "smart-front" in text
        assert "claude" in text
        assert "55470" in text
        assert "bash×20, gh×4" in text

    def test_sources_beyond_the_table_are_summed_so_the_rows_add_up_to_the_total(self) -> None:
        """表に出さない起動元の分を 1 行で足す(行の合計と見出しの本数が食い違わないように)。"""
        sources = tuple(
            ChurnSource(pid=100 + i, command="bash", origin=None, children=("x",) * (20 - i))
            for i in range(render.CHURN_TOP_SOURCES + 2)
        )
        found = Churn(seconds=3.0, sources=sources)
        rest = sources[render.CHURN_TOP_SOURCES :]
        row = next(line for line in self._text(found).splitlines() if "ほか" in line)
        assert f"ほか {len(rest)} 起動元" in row
        assert f" {sum(s.count for s in rest)} " in row

    def test_no_remainder_row_when_every_source_fits(self) -> None:
        source = ChurnSource(pid=100, command="bash", origin=None, children=("x",))
        assert "ほか" not in self._text(Churn(seconds=3.0, sources=(source,)))

    def test_unknown_parent_is_labelled(self) -> None:
        source = ChurnSource(pid=CHURN_UNKNOWN_PARENT, command="", origin=None, children=("bash",))
        assert "(親不明)" in self._text(Churn(seconds=3.0, sources=(source,)))

    def test_nothing_found(self) -> None:
        assert "0 本" in self._text(Churn(seconds=3.0, sources=()))

    def test_untrusted_command_is_not_interpreted_as_markup(self) -> None:
        source = ChurnSource(pid=1, command="[red]x[/red]", origin=None, children=("[b]y[/b]",))
        text = self._text(Churn(seconds=3.0, sources=(source,)))
        assert "[b]y[/b]" in text

    def test_json_carries_the_breakdown(self) -> None:
        import json

        source = ChurnSource(
            pid=100,
            command="claude",
            origin=Origin(kind="git", name="pj"),
            children=("bash", "bash"),
        )
        payload = json.loads(
            render.build_json(
                [], SystemMemory(None, None, None), SystemCpu(None, None), Churn(3.0, (source,))
            )
        )
        assert payload["churn"]["total"] == 2
        assert payload["churn"]["sources"][0]["pid"] == 100
        assert payload["churn"]["sources"][0]["origin"] == {"kind": "git", "name": "pj"}
        assert payload["churn"]["sources"][0]["children"] == {"bash": 2}

    def test_json_omits_churn_when_not_measured(self) -> None:
        import json

        payload = json.loads(
            render.build_json([], SystemMemory(None, None, None), SystemCpu(None, None))
        )
        assert "churn" not in payload


class _SpyConsole:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def clear(self) -> None:
        self.events.append("clear")

    def print(self, *args: object, **kwargs: object) -> None:
        pass


@pytest.mark.parametrize("view", ["processes", "app", "group", "project"])
@pytest.mark.parametrize(("order", "measured"), [("cpu", True), ("mem", False)])
def test_churn_is_measured_only_for_the_cpu_order(
    monkeypatch: pytest.MonkeyPatch, view: str, order: str, measured: bool
) -> None:
    """CPU 順(cpuhog)の全表示で数え、実メモリ順(memhog)では数えない(数秒かかるため)。

    データを集め終えてから画面を消す約束も、数える分を含めて守る。
    """
    events: list[str] = []
    def built(*rest: object) -> object:
        events.append("build")
        return ([], *rest)

    monkeypatch.setattr(report, "build_processes", lambda *a: built(""))
    monkeypatch.setattr(report, "build_app_processes", lambda *a: built(""))
    monkeypatch.setattr(report, "build_groups", lambda *a: built(""))
    monkeypatch.setattr(report, "build_projects", lambda *a: built(None, ""))
    monkeypatch.setattr(report, "build_system_memory", lambda raw: SystemMemory(None, None, None))
    monkeypatch.setattr(report, "build_system_cpu", lambda raw: SystemCpu(None, None))
    monkeypatch.setattr(
        report, "build_churn", lambda *a: events.append("churn") or Churn(3.0, ())
    )
    for name in ("render_table", "render_group_table", "render_project_table"):
        monkeypatch.setattr(render, name, lambda *a, **k: events.append("render"))
    monkeypatch.setattr(render, "render_churn", lambda *a, **k: events.append("render_churn"))

    cli._render_view(_SpyConsole(events), view, 5, None, order, "x", clear=True)  # type: ignore[arg-type]
    if measured:
        assert events == ["build", "churn", "clear", "render", "render_churn"]
    else:
        assert events == ["build", "clear", "render"]
