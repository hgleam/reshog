"""開始時刻(起動列)のテスト。

ps の lstart は曜日・月名がロケールで変わるため使わない。経過時間(etime)は
数字と記号だけなので、「いま - 経過」で開始時刻を出す。
"""

import io
import json
from datetime import datetime

import pytest
from rich.console import Console

from reshog import collect, report
from reshog.models import Process, SystemCpu, SystemMemory
from reshog.parse import parse_etime_seconds, parse_ps_etime
from reshog.render import build_json, render_table


class TestParseEtimeSeconds:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("00:05", 5),
            ("12:34", 12 * 60 + 34),
            ("21:20:22", 21 * 3600 + 20 * 60 + 22),
            ("3-01:02:03", 3 * 86400 + 3600 + 2 * 60 + 3),
            ("123-00:00:00", 123 * 86400),
        ],
    )
    def test_formats(self, value: str, expected: int) -> None:
        assert parse_etime_seconds(value) == expected

    @pytest.mark.parametrize("value", ["", "-", "abc", "1:2:3:4"])
    def test_unparsable(self, value: str) -> None:
        assert parse_etime_seconds(value) is None


class TestParsePsEtime:
    def test_maps_pid_to_seconds(self) -> None:
        out = "20193 21:20:22\n  172 3-01:02:03\n"
        assert parse_ps_etime(out) == {20193: 76822, 172: 3 * 86400 + 3723}

    def test_skips_broken_lines(self) -> None:
        assert parse_ps_etime("garbage\n42\n") == {}


class TestProcessElapsedCommand:
    def test_one_call_for_all_pids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[list[str]] = []
        monkeypatch.setattr(collect, "_run", lambda args: seen.append(args) or "")
        collect.process_elapsed([20193, 2299])
        assert seen == [["ps", "-o", "pid=,etime=", "-p", "20193,2299"]]

    def test_no_pids_runs_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[list[str]] = []
        monkeypatch.setattr(collect, "_run", lambda args: seen.append(args) or "")
        assert collect.process_elapsed([]) == ""
        assert seen == []


_TOP = """\
PID    MEM   %CPU
20193  4700M 0.0
2299   900M  0.0
"""
_NOW = datetime(2026, 9, 29, 10, 0, 0)


class TestBuildProcessesAttachesStart:
    @pytest.fixture(autouse=True)
    def _mock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(collect, "top_sample", lambda count, order="mem": _TOP)
        monkeypatch.setattr(collect, "ps_command", lambda pid: f"/bin/cmd{pid}")
        monkeypatch.setattr(collect, "ps_rss_mb", lambda pid: 10)
        monkeypatch.setattr(collect, "process_cwds", lambda pids: "")
        monkeypatch.setattr(collect, "launchd_jobs", lambda: "")
        # 2299 は ps が拾えなかった(直前に終了した)想定。
        monkeypatch.setattr(collect, "process_elapsed", lambda pids: "20193 21:20:22\n")
        monkeypatch.setattr(report, "_now", lambda: _NOW)

    def test_start_is_now_minus_elapsed(self) -> None:
        procs, _ = report.build_processes(count=10)
        assert procs[0].started_at == datetime(2026, 9, 28, 12, 39, 38)

    def test_unknown_start_is_none(self) -> None:
        procs, _ = report.build_processes(count=10)
        assert procs[1].started_at is None


_SYSTEM = SystemMemory(phys=None, swap=None, free_percentage=None)
_CPU = SystemCpu(load_average=None, usage=None)


def _proc(pid: int, started: datetime | None) -> Process:
    return Process(pid=pid, mem_mb=100, rss_mb=10, cpu=0.0, command="/bin/x", started_at=started)


class TestRender:
    def _text(self, processes: list[Process]) -> str:
        buffer = io.StringIO()
        console = Console(file=buffer, width=200, no_color=True, highlight=False)
        render_table(console, processes, _SYSTEM, _CPU)
        return buffer.getvalue()

    def test_table_shows_start(self) -> None:
        out = self._text([_proc(1, datetime(2026, 9, 28, 12, 39, 38))])
        assert "起動" in out
        assert "09-28 12:39" in out

    def test_unknown_start_is_dash(self, cell) -> None:
        assert cell(self._text([_proc(4242, None)]), 4242, "起動") == "-"

    def test_json_has_iso_start(self) -> None:
        payload = json.loads(
            build_json([_proc(1, datetime(2026, 9, 28, 12, 39, 38)), _proc(2, None)], _SYSTEM, _CPU)
        )
        assert payload["processes"][0]["started_at"] == "2026-09-28T12:39:38"
        assert payload["processes"][1]["started_at"] is None
