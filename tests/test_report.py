"""report モジュールの単体テスト(collect をモックして top を叩かない)。"""

import pytest

from reshog import collect, report

TOP_SAMPLE = """\
PhysMem: 63G used (7613M wired, 32G compressor), 217M unused.

PID    MEM   %CPU
28632  32G   0.0
69624  8112M 0.0
29473  6759M 0.1
"""

_COMMANDS = {
    28632: "/usr/bin/python main.py --port 8188",
    69624: "com.apple.Virtualization.VirtualMachine",
    29473: "/opt/homebrew/bin/llama-server --port 8080",
}
_RSS = {28632: 26, 69624: 2600, 29473: 12}

# ps -Ao pid=,ppid=,rss=,command= 相当。28632 は 69624 の子(= 同じアプリに畳まれる)。
PS_SNAPSHOT = """\
28632 69624    26624 /usr/bin/python main.py --port 8188
69624     1  2662400 com.apple.Virtualization.VirtualMachine
29473     1    12288 /opt/homebrew/bin/llama-server --port 8080
"""


@pytest.fixture(autouse=True)
def _mock_collect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collect, "top_sample", lambda count, order="mem": TOP_SAMPLE)
    monkeypatch.setattr(collect, "ps_command", lambda pid: _COMMANDS.get(pid, ""))
    monkeypatch.setattr(collect, "ps_rss_mb", lambda pid: _RSS.get(pid, 0))
    monkeypatch.setattr(collect, "ps_snapshot", lambda: PS_SNAPSHOT)
    monkeypatch.setattr(collect, "swap_usage", lambda: "total = 32768.00M  used = 31855.94M")
    monkeypatch.setattr(collect, "memory_pressure", lambda: "free percentage: 37%\n")
    # PJ 列・起動列の材料。実マシンのプロセスを引かせない(中身は test_origin / test_started)。
    monkeypatch.setattr(collect, "process_cwds", lambda pids: "")
    monkeypatch.setattr(collect, "launchd_jobs", lambda: "")
    monkeypatch.setattr(collect, "process_elapsed", lambda pids: "")
    # llama-server の休止状態の問い合わせ(中身は test_llama_sleep)。実際の口へ繋がせない。
    monkeypatch.setattr(collect, "http_get", lambda url: "")


class TestBuildProcesses:
    def test_builds_all(self) -> None:
        procs, _ = report.build_processes(count=10)
        assert [p.pid for p in procs] == [28632, 69624, 29473]
        assert procs[0].mem_mb == 32768
        assert procs[0].rss_mb == 26
        assert procs[0].hidden_gpu is True
        assert procs[1].hidden_gpu is False

    def test_respects_count(self) -> None:
        procs, _ = report.build_processes(count=2)
        assert len(procs) == 2

    def test_filters_by_pattern(self) -> None:
        procs, _ = report.build_processes(count=10, pattern="python")
        assert [p.pid for p in procs] == [28632]

    def test_rss_is_read_only_for_shown_processes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """RSS(ps を 1 回叩く)は、絞り込みと件数に通ったものだけに取る。

        上位 N 件の表示は候補を多めに取るので、全候補に ps を叩くと呼び出しが膨らむ。
        """
        asked: list[int] = []
        monkeypatch.setattr(collect, "ps_rss_mb", lambda pid: asked.append(pid) or 0)
        report.build_processes(count=1)
        assert asked == [28632]
        asked.clear()
        report.build_processes(count=10, pattern="llama")
        assert asked == [29473]

    def test_pattern_is_case_insensitive(self) -> None:
        procs, _ = report.build_processes(count=10, pattern="LLAMA")
        assert [p.pid for p in procs] == [29473]

    def test_skips_pid_without_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            collect, "ps_command", lambda pid: "" if pid == 69624 else _COMMANDS[pid]
        )
        procs, _ = report.build_processes(count=10)
        assert 69624 not in [p.pid for p in procs]


class TestBuildSystemMemory:
    def test_builds(self) -> None:
        system = report.build_system_memory(TOP_SAMPLE)
        assert system.phys == "63G used (7613M wired, 32G compressor), 217M unused."
        assert system.free_percentage == "37%"
        assert system.swap is not None


class TestBuildGroups:
    def test_groups_children_into_the_parent_app(self) -> None:
        groups, _ = report.build_groups(count=10)
        labels = {g.label: g for g in groups}
        assert set(labels) == {"com.apple.Virtualization.VirtualMachine", "llama-server"}
        vm = labels["com.apple.Virtualization.VirtualMachine"]
        assert vm.count == 2
        assert vm.total_mb == 32768 + 8112
        assert vm.hidden_gpu is True

    def test_sorted_by_total_desc(self) -> None:
        groups, _ = report.build_groups(count=10)
        assert [g.total_mb for g in groups] == sorted(
            (g.total_mb for g in groups), reverse=True
        )

    def test_respects_count(self) -> None:
        assert len(report.build_groups(count=1)[0]) == 1

    def test_filters_before_grouping(self) -> None:
        groups, _ = report.build_groups(count=10, pattern="llama")
        assert [(g.label, g.count) for g in groups] == [("llama-server", 1)]


class TestGroupSampleWidth:
    """top の走査幅が ps の実プロセス数に追随する(固定上限で黙って切らない)。"""

    def test_sample_count_covers_all_processes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        many = "\n".join(
            f"{pid} 1 1024 /usr/bin/proc{pid}" for pid in range(1000, 1000 + 800)
        )
        monkeypatch.setattr(collect, "ps_snapshot", lambda: many)
        requested: list[int] = []

        def _top(count: int, order: str = "mem") -> str:
            requested.append(count)
            return TOP_SAMPLE

        monkeypatch.setattr(collect, "top_sample", _top)
        report.build_groups(count=10)
        assert requested and requested[0] >= 800

    def test_sample_count_has_a_floor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(collect, "ps_snapshot", lambda: "")
        requested: list[int] = []

        def _top(count: int, order: str = "mem") -> str:
            requested.append(count)
            return TOP_SAMPLE

        monkeypatch.setattr(collect, "top_sample", _top)
        report.build_groups(count=10)
        assert requested == [report.GROUP_SAMPLE_MIN]


class TestBuildAppProcesses:
    """--app の内訳は、コマンド文字列でなく親子関係(--group と同じ規則)で絞る。"""

    def test_picks_children_whose_command_lacks_the_app_name(self) -> None:
        procs, _ = report.build_app_processes("com.apple.Virtualization.VirtualMachine", 10)
        # 28632 は python だが、親が VirtualMachine なので内訳に入る(-g では拾えない)。
        assert [p.pid for p in procs] == [28632, 69624]

    def test_label_is_case_insensitive(self) -> None:
        procs, _ = report.build_app_processes("LLAMA-SERVER", 10)
        assert [p.pid for p in procs] == [29473]

    def test_respects_count(self) -> None:
        procs, _ = report.build_app_processes("com.apple.Virtualization.VirtualMachine", 1)
        assert len(procs) == 1

    def test_unknown_label_is_empty(self) -> None:
        procs, _ = report.build_app_processes("no-such-app", 10)
        assert procs == []
