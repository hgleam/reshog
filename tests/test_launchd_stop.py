"""launchd の常駐ジョブを止める案内のテスト。

KeepAlive のジョブは kill しても launchd がすぐ起動し直す。利用者が案内どおり
`kill <PID>` を打つと、別の PID で立ち上がり、同じ PID でもう一度打つと
「no such process」になる(2026-09-29 に実際に起きた)。ジョブは launchctl bootout で止める。

PJ 列(origin)とは別に持つ: llama-server は PJ が tokyo-calendar(作業ディレクトリのリポ名)
でも、面倒を見ているのは launchd のジョブ。PJ 列だけでは常駐ジョブかどうか分からない。
"""

import io
import json
from pathlib import Path

import pytest
import typer
from rich.console import Console

from reshog import cli, collect, control, origin, report
from reshog.models import Process, SystemCpu, SystemMemory
from reshog.render import build_json, render_table, stop_command

_TOP = "PID MEM %CPU\n20193 4700M 0.0\n2299 900M 0.0\n"
_JOBS = (
    "PID\tStatus\tLabel\n"
    "20193\t0\tcom.tokyocal.llama-server\n"
    "2299\t0\tapplication.com.docker.docker.1234.5678\n"
)


class TestLaunchdService:
    def test_user_job_is_in_the_gui_domain(self) -> None:
        got = origin.launchd_service("com.tokyocal.llama-server", "gui/501")
        assert got == "gui/501/com.tokyocal.llama-server"

    def test_root_sees_the_system_domain(self) -> None:
        """sudo で走らせると launchctl list は system のジョブを返す。gui/ で案内すると失敗する。"""
        assert origin.launchd_service("com.example.daemon", "system") == "system/com.example.daemon"

    def test_gui_app_is_not_a_job_to_boot_out(self) -> None:
        """GUI アプリの自動ラベルは乱数付きで、kill で普通に止まる。"""
        assert origin.launchd_service("application.com.docker.docker.1234.5678", "gui/501") is None
        assert origin.launchd_service(None, "gui/501") is None

    def test_apple_agents_are_not_booted_out(self) -> None:
        """bootout はジョブを台帳から外す。

        OS のエージェントに勧めると再ログインまで機能が欠ける。
        """
        assert origin.launchd_service("com.apple.trustd.agent", "gui/501") is None


class TestReportAttachesJob:
    @pytest.fixture(autouse=True)
    def _mock(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        repo = tmp_path / "tokyo-calendar"
        (repo / ".git").mkdir(parents=True)
        monkeypatch.setattr(collect, "top_sample", lambda count, order="mem": _TOP)
        monkeypatch.setattr(collect, "ps_command", lambda pid: f"/bin/cmd{pid}")
        monkeypatch.setattr(collect, "ps_rss_mb", lambda pid: 10)
        monkeypatch.setattr(collect, "process_cwds", lambda pids: f"p20193\nfcwd\nn{repo}\n")
        monkeypatch.setattr(collect, "launchd_jobs", lambda: _JOBS)
        monkeypatch.setattr(collect, "process_elapsed", lambda pids: "")
        monkeypatch.setattr(collect, "launchd_domain", lambda: "gui/501")

    def test_job_is_kept_even_when_pj_is_a_repo(self) -> None:
        procs, _ = report.build_processes(count=10)
        assert procs[0].origin is not None and procs[0].origin.name == "tokyo-calendar"
        assert procs[0].launchd_service == "gui/501/com.tokyocal.llama-server"

    def test_gui_app_has_no_job(self) -> None:
        procs, _ = report.build_processes(count=10)
        assert procs[1].launchd_service is None


def _proc(pid: int, service: str | None) -> Process:
    return Process(
        pid=pid, mem_mb=100, rss_mb=100, cpu=0.0, command="/bin/x", launchd_service=service
    )


_SYSTEM = SystemMemory(phys=None, swap=None, free_percentage=None)
_CPU = SystemCpu(load_average=None, usage=None)


def _footer(p: Process) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, width=200, no_color=True, highlight=False)
    render_table(console, [p], _SYSTEM, _CPU)
    return buffer.getvalue()


class TestStopHint:
    def test_job_is_booted_out_not_killed(self) -> None:
        out = _footer(_proc(20193, "gui/501/com.tokyocal.llama-server"))
        assert "launchctl bootout gui/501/com.tokyocal.llama-server" in out
        assert "kill 20193" not in out

    def test_restore_hint_names_the_domain(self) -> None:
        """戻し方も、どのドメインへ何を渡すかまで書く(plist のパスは reshog には分からない)。"""
        assert "launchctl bootstrap gui/501 <plist のパス>" in _footer(
            _proc(20193, "gui/501/com.tokyocal.llama-server")
        )

    def test_plain_process_is_killed(self) -> None:
        assert "kill 2299" in _footer(_proc(2299, None))

    def test_label_is_shell_quoted(self) -> None:
        """ラベルは他プロセス由来の文字列。貼り付けて実行される前提なので quote する。"""
        got = stop_command(_proc(1, "gui/501/a;rm -rf ~"))
        assert got == "launchctl bootout 'gui/501/a;rm -rf ~'"

    def test_json_has_job(self) -> None:
        payload = json.loads(build_json([_proc(1, "gui/501/com.x"), _proc(2, None)], _SYSTEM, _CPU))
        assert [p["launchd_service"] for p in payload["processes"]] == ["gui/501/com.x", None]


class TestKillWarnsForJobs:
    def _run(self, monkeypatch: pytest.MonkeyPatch, target: Process) -> tuple[str, list[int]]:
        sent: list[int] = []
        monkeypatch.setattr(typer, "prompt", lambda *a, **k: target.pid)
        monkeypatch.setattr(typer, "confirm", lambda *a, **k: True)
        monkeypatch.setattr(control, "current_pid", lambda: 1)
        monkeypatch.setattr(control, "send_signal", lambda pid, sig: sent.append(pid) or "ok")
        buffer = io.StringIO()
        console = Console(file=buffer, width=200, no_color=True, highlight=False)
        cli._kill_process([target], console, force=False, assume_yes=False)
        return buffer.getvalue(), sent

    def test_job_gets_a_warning_and_the_bootout_command(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        out, sent = self._run(monkeypatch, _proc(20193, "gui/501/com.tokyocal.llama-server"))
        assert "起動し直" in out
        assert "launchctl bootout gui/501/com.tokyocal.llama-server" in out
        assert sent == [20193], "警告しても、利用者が確認したら送る(止める手段を奪わない)"

    def test_plain_process_gets_no_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        out, sent = self._run(monkeypatch, _proc(2299, None))
        assert "起動し直" not in out
        assert sent == [2299]



class TestLaunchdDomain:
    def test_user(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(collect.os, "geteuid", lambda: 501)
        assert collect.launchd_domain() == "gui/501"

    def test_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(collect.os, "geteuid", lambda: 0)
        assert collect.launchd_domain() == "system"
