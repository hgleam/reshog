"""llama-server の休止状態(💤 休止中 / ▶ 稼働中)と、その状態になった時刻のテスト。

`--sleep-idle-seconds` の休止は同じプロセスのままモデルを外すだけなので、「起動」列
(プロセスの開始時刻)は変わらない。いまメモリを掴んでいるか・いつからかを別に出す。

- 状態: `/props` の `is_sleeping`(読むだけで休止中のサーバーを起こさない。2026-09-29 に実測)
- 時刻: ログの `entering / exiting sleeping state` 行。時刻は起動からの `分.秒.ミリ.マイクロ` なので
  プロセスの開始時刻に足す。起動し直すと 0 に戻り、同じファイルに続けて書かれる。
"""

import io
import json
from datetime import datetime, timedelta

import pytest
from rich.console import Console

from reshog import collect, llama, report
from reshog.models import LlmState, Process, SystemCpu, SystemMemory
from reshog.parse import parse_launchctl_stderr_path, parse_llama_props
from reshog.render import build_json, render_table

LLAMA = (
    "/opt/homebrew/bin/llama-server -hf unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF:Q4_K_M "
    "--host 127.0.0.1 --port 8090 -c 32768 --sleep-idle-seconds 1800"
)

# 実ログの形(tokyo-calendar の llama-server-stderr.log から)。前の起動の分が先に残っている。
LOG = """\
111.05.573.860 I srv    operator(): cleaning up
0.01.008.603 I log_info: build = 1
5.05.368.378 I srv  handle_sleep: server is entering sleeping state
60.00.101.330 I srv  handle_sleep: server is exiting sleeping state
61.24.868.755 I srv  update_slots: all slots are idle
                continuation line without a timestamp
66.25.652.815 I srv  handle_sleep: server is entering sleeping state
69.45.651.499 I srv  handle_sleep: server is exiting sleeping state
76.10.820.435 I srv  handle_sleep: server is entering sleeping state
"""


class TestEndpoint:
    def test_host_and_port_from_the_command(self) -> None:
        assert llama.endpoint(LLAMA) == ("127.0.0.1", 8090)

    def test_defaults(self) -> None:
        assert llama.endpoint("/opt/homebrew/bin/llama-server -m x.gguf") == ("127.0.0.1", 8080)

    def test_equals_form(self) -> None:
        assert llama.endpoint("llama-server --port=9000 --host=localhost") == ("127.0.0.1", 9000)

    def test_any_address_is_asked_on_loopback(self) -> None:
        assert llama.endpoint("llama-server --host 0.0.0.0 --port 8090") == ("127.0.0.1", 8090)

    def test_remote_host_is_not_asked(self) -> None:
        """他のマシンへは問い合わせない(診断のついでに外へ通信しない)。"""
        assert llama.endpoint("llama-server --host 192.168.1.5 --port 8090") is None

    @pytest.mark.parametrize("command", ["/usr/bin/python llama-server.py", "ollama serve", ""])
    def test_not_llama_server(self, command: str) -> None:
        assert llama.endpoint(command) is None


class TestParse:
    def test_props(self) -> None:
        assert parse_llama_props('{"is_sleeping": true, "total_slots": 4}') is True
        assert parse_llama_props('{"is_sleeping": false}') is False

    @pytest.mark.parametrize("raw", ["", "not json", '{"total_slots": 4}', "[]"])
    def test_props_unknown(self, raw: str) -> None:
        assert parse_llama_props(raw) is None

    def test_launchctl_stderr_path(self) -> None:
        raw = (
            "gui/501/com.x = {\n\tstdout path = /tmp/out.log\n"
            "\tstderr path = /Users/me/logs/llama-server-stderr.log\n}\n"
        )
        assert parse_launchctl_stderr_path(raw) == "/Users/me/logs/llama-server-stderr.log"
        assert parse_launchctl_stderr_path("") is None


class TestLastTransition:
    def test_last_entering(self) -> None:
        assert llama.last_transition(LOG) == (True, timedelta(minutes=76, seconds=10))

    def test_last_exiting(self) -> None:
        text = LOG.rsplit("\n", 2)[0] + "\n"  # 最後の entering を落とす
        assert llama.last_transition(text) == (False, timedelta(minutes=69, seconds=45))

    def test_previous_run_is_ignored(self) -> None:
        """起動し直した後に休止の出入りが無ければ、前の起動の行を使わない。"""
        text = "90.00.000.000 I srv  handle_sleep: server is entering sleeping state\n"
        text += "0.02.000.000 I log_info: build = 1\n"
        assert llama.last_transition(text) is None

    def test_no_transition(self) -> None:
        assert llama.last_transition("0.01.000.000 I log_info: build = 1\n") is None
        assert llama.last_transition("") is None


_TOP = "PID MEM %CPU\n34758 3100M 0.0\n2299 900M 0.0\n"
_START = datetime(2026, 9, 29, 13, 5, 9)


class TestReport:
    @pytest.fixture(autouse=True)
    def _mock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.asked: list[str] = []
        commands = {34758: LLAMA, 2299: "/usr/bin/other"}
        monkeypatch.setattr(collect, "top_sample", lambda count, order="mem": _TOP)
        monkeypatch.setattr(collect, "ps_command", lambda pid: commands[pid])
        monkeypatch.setattr(collect, "ps_rss_mb", lambda pid: 10)
        monkeypatch.setattr(collect, "process_cwds", lambda pids: "")
        monkeypatch.setattr(
            collect, "launchd_jobs", lambda: "PID\tStatus\tLabel\n34758\t0\tcom.tokyocal.llama\n"
        )
        monkeypatch.setattr(collect, "launchd_domain", lambda: "gui/501")
        # 開始 13:05:09 = いま 14:58:41 − 経過 1:53:32
        monkeypatch.setattr(collect, "process_elapsed", lambda pids: "34758 01:53:32\n")
        monkeypatch.setattr(report, "_now", lambda: datetime(2026, 9, 29, 14, 58, 41))

        def _get(url: str) -> str:
            self.asked.append(url)
            return '{"is_sleeping": true}'

        monkeypatch.setattr(collect, "http_get", _get)
        monkeypatch.setattr(
            collect,
            "launchd_print",
            lambda service: "\tstderr path = /logs/llama-server-stderr.log\n",
        )
        monkeypatch.setattr(collect, "read_tail", lambda path: LOG if path.endswith(".log") else "")

    def test_sleeping_since_the_last_entering(self) -> None:
        procs, _ = report.build_processes(count=10)
        since = datetime(2026, 9, 29, 14, 21, 19)
        assert procs[0].llm_state == LlmState(sleeping=True, since=since)

    def test_only_llama_server_is_asked(self) -> None:
        procs, _ = report.build_processes(count=10)
        assert self.asked == ["http://127.0.0.1:8090/props"]
        assert procs[1].llm_state is None

    def test_state_without_a_log_has_no_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """launchd のジョブでなければログの場所が分からない。状態だけ出す(時刻は推測しない)。"""
        monkeypatch.setattr(collect, "launchd_jobs", lambda: "")
        procs, _ = report.build_processes(count=10)
        assert procs[0].llm_state == LlmState(sleeping=True, since=None)

    def test_time_is_dropped_when_the_log_disagrees(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """/props は稼働中なのにログの最後が休止入り(ログが遅れている等)なら、時刻を出さない。"""
        monkeypatch.setattr(collect, "http_get", lambda url: '{"is_sleeping": false}')
        procs, _ = report.build_processes(count=10)
        assert procs[0].llm_state == LlmState(sleeping=False, since=None)

    def test_unreachable_server_has_no_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(collect, "http_get", lambda url: "")
        procs, _ = report.build_processes(count=10)
        assert procs[0].llm_state is None


_SYSTEM = SystemMemory(phys=None, swap=None, free_percentage=None)
_CPU = SystemCpu(load_average=None, usage=None)


def _proc(state: LlmState | None) -> Process:
    return Process(pid=7, mem_mb=3100, rss_mb=3100, cpu=0.0, command=LLAMA, llm_state=state)


def _cell(cell, state: LlmState | None) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, width=400, no_color=True, highlight=False)
    render_table(console, [_proc(state)], _SYSTEM, _CPU)
    return cell(buffer.getvalue(), 7, "COMMAND")


class TestRender:
    def test_sleeping(self, cell) -> None:
        state = LlmState(sleeping=True, since=datetime(2026, 9, 29, 14, 21, 19))
        assert "💤 休止中(14:21 から)" in _cell(cell, state)

    def test_running(self, cell) -> None:
        state = LlmState(sleeping=False, since=datetime(2026, 9, 29, 14, 14, 54))
        assert "▶ 稼働中(14:14 に復帰)" in _cell(cell, state)

    def test_time_unknown(self, cell) -> None:
        text = _cell(cell, LlmState(sleeping=True, since=None))
        assert "💤 休止中" in text and "から" not in text

    def test_unknown_state_shows_nothing(self, cell) -> None:
        text = _cell(cell, None)
        assert "休止中" not in text and "稼働中" not in text

    def test_json(self) -> None:
        state = LlmState(sleeping=True, since=datetime(2026, 9, 29, 14, 21, 19))
        payload = json.loads(build_json([_proc(state), _proc(None)], _SYSTEM, _CPU))
        assert payload["processes"][0]["llm_state"] == {
            "sleeping": True,
            "since": "2026-09-29T14:21:19",
        }
        assert payload["processes"][1]["llm_state"] is None


class TestCollect:
    def test_read_tail_reads_only_the_end(self, tmp_path) -> None:
        f = tmp_path / "x.log"
        f.write_text("a" * 100 + "\nlast line\n")
        assert collect.read_tail(str(f), max_bytes=20).endswith("last line\n")
        assert len(collect.read_tail(str(f), max_bytes=20)) <= 20

    def test_read_tail_missing_file(self, tmp_path) -> None:
        assert collect.read_tail(str(tmp_path / "gone.log")) == ""
