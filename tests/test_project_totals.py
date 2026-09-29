"""PJ 別の合計(--project)のテスト。

「どのプロジェクトが一番食っているか」に答える。全プロセスを走査して、PJ 列と同じ
判定(origin.resolve)で束ね、合計の降順に並べる。PJ が分からないものは順位に混ぜず
別に合計を出す(GUI アプリが「-」として 1 位に居座り、PJ の比較が見えなくなるため)。
"""

import io
import json
from pathlib import Path

import pytest
from rich.console import Console

from reshog import aggregate, collect, origin, report
from reshog.models import Origin, Process, ProcessGroup, SystemCpu, SystemMemory
from reshog.render import build_project_json, render_project_table

_TOP = """\
PID    MEM   %CPU
100    4000M 1.0
200    1000M 30.0
300    2000M 0.0
400    9000M 5.0
500    500M  0.0
"""
_PS = """\
100 1 1024 /opt/homebrew/bin/llama-server
200 1 1024 /Users/me/.local/bin/claude
300 1 1024 /usr/bin/python worker.py
400 1 1024 /Applications/Chrome.app/Contents/MacOS/Chrome
500 1 1024 /usr/libexec/daemon
"""


@pytest.fixture
def repos(tmp_path: Path) -> dict[str, Path]:
    found = {}
    for name in ("tokyo-calendar", "smart-front"):
        (tmp_path / name / ".git").mkdir(parents=True)
        found[name] = tmp_path / name
    return found


@pytest.fixture(autouse=True)
def _mock(monkeypatch: pytest.MonkeyPatch, repos: dict[str, Path]) -> list[list[int]]:
    lsof_calls: list[list[int]] = []

    def _cwd(pids: list[int]) -> str:
        lsof_calls.append(sorted(pids))
        return (
            f"p100\nfcwd\nn{repos['tokyo-calendar']}\n"
            f"p200\nfcwd\nn{repos['smart-front']}\n"
            f"p300\nfcwd\nn{repos['tokyo-calendar']}\n"
            "p400\nfcwd\nn/\n"
            "p500\nfcwd\nn/\n"
        )

    monkeypatch.setattr(collect, "ps_snapshot", lambda: _PS)
    monkeypatch.setattr(collect, "top_sample", lambda count, order="mem": _TOP)
    monkeypatch.setattr(collect, "process_cwds", _cwd)
    jobs = "PID\tStatus\tLabel\n500\t0\tcom.me.daemon\n"
    monkeypatch.setattr(collect, "launchd_jobs", lambda: jobs)
    monkeypatch.setattr(collect, "process_elapsed", lambda pids: "")
    return lsof_calls


class TestBuildProjects:
    def test_ranks_projects_by_total_memory(self) -> None:
        projects, _, _ = report.build_projects(count=10)
        assert [(g.label, g.total_mb) for g in projects] == [
            ("tokyo-calendar", 6000),
            ("smart-front", 1000),
            ("launchd:com.me.daemon", 500),
        ]

    def test_cpu_order_ranks_by_total_cpu(self) -> None:
        projects, _, _ = report.build_projects(count=10, order="cpu")
        assert projects[0].label == "smart-front"

    def test_unknown_is_kept_out_of_the_ranking(self) -> None:
        """Chrome(9000M)は PJ 不明。順位に入れると 1 位に居座る。別に合計する。"""
        projects, unknown, _ = report.build_projects(count=10)
        assert all(g.label != "-" for g in projects)
        assert unknown is not None
        assert (unknown.total_mb, unknown.count) == (9000, 1)

    def test_nothing_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        only_known = "PID MEM %CPU\n100 4000M 1.0\n"
        monkeypatch.setattr(collect, "top_sample", lambda count, order="mem": only_known)
        _, unknown, _ = report.build_projects(count=10)
        assert unknown is None

    def test_count_limits_projects(self) -> None:
        projects, _, _ = report.build_projects(count=1)
        assert [g.label for g in projects] == ["tokyo-calendar"]

    def test_grep_filters_before_totalling(self) -> None:
        projects, _, _ = report.build_projects(count=10, pattern="llama")
        assert [(g.label, g.total_mb) for g in projects] == [("tokyo-calendar", 4000)]

    def test_all_processes_in_one_lsof_call(self, _mock: list[list[int]]) -> None:
        report.build_projects(count=1)
        assert _mock == [[100, 200, 300, 400, 500]]

    def test_members_carry_their_origin(self) -> None:
        projects, _, _ = report.build_projects(count=10)
        assert projects[0].members[0].origin == Origin(kind="git", name="tokyo-calendar")


class TestLabelIsSharedWithTheColumn:
    """PJ 列の表記と合計の束ね方がずれると、列で見た名前が合計に無い。同じ関数を使う。"""

    def test_launchd_label(self) -> None:
        assert origin.label(Origin(kind="launchd", name="com.me.daemon")) == "launchd:com.me.daemon"

    def test_git_label(self) -> None:
        assert origin.label(Origin(kind="git", name="tokyo-calendar")) == "tokyo-calendar"


class TestBucketProcesses:
    def test_group_processes_is_bucketing_by_app(self) -> None:
        """アプリ別(--group)と PJ 別(--project)は、束ねるキーだけが違う同じ集約。"""
        procs = [
            Process(pid=1, mem_mb=10, rss_mb=1, cpu=0.0, command="a"),
            Process(pid=2, mem_mb=30, rss_mb=1, cpu=0.0, command="b"),
        ]
        got = aggregate.bucket_processes(procs, lambda p: "x", "mem")
        assert [(g.label, g.total_mb, g.largest.pid) for g in got] == [("x", 40, 2)]


_SYSTEM = SystemMemory(phys=None, swap=None, free_percentage=None)
_CPU = SystemCpu(load_average=None, usage=None)


def _group(label: str, mb: int) -> ProcessGroup:
    return ProcessGroup(
        label=label, members=(Process(pid=7, mem_mb=mb, rss_mb=mb, cpu=0.0, command="/bin/x"),)
    )


class TestRender:
    def _text(self, unknown: ProcessGroup | None) -> str:
        buffer = io.StringIO()
        console = Console(file=buffer, width=200, no_color=True, highlight=False)
        render_project_table(console, [_group("tokyo-calendar", 6000)], unknown, _SYSTEM, _CPU)
        return buffer.getvalue()

    def test_header_says_pj(self, cell) -> None:
        out = self._text(None)
        assert "PJ 別" in out
        assert cell(out, 7, "PJ") == "tokyo-calendar"

    def test_unknown_total_is_shown_separately(self) -> None:
        out = self._text(_group("-", 9000))
        assert "PJ 不明" in out
        assert "8.8G" in out

    def test_no_app_drilldown_suggestion(self) -> None:
        """--app は APP 名しか受け取らない。PJ 名を渡す提案は打っても何も出ない。"""
        assert "--app" not in self._text(None)

    def test_json(self) -> None:
        payload = json.loads(
            build_project_json([_group("tokyo-calendar", 6000)], _group("-", 9000), _SYSTEM, _CPU)
        )
        assert payload["projects"][0]["label"] == "tokyo-calendar"
        assert payload["unknown"] == {"total_mb": 9000, "total_cpu": 0.0, "count": 1}
        assert "groups" not in payload
