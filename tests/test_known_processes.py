"""OS のプロセスに「何のためのものか・止めてよいか」を添えるテスト。

上位に WindowServer が出ても、名前だけでは何のためのものか分からず、案内どおり
kill すると画面が落ちてログアウトと同じになる(2026-09-29 に「これは何？」と聞かれた)。
"""

import io

import pytest
import typer
from rich.console import Console

from reshog import cli, control, known
from reshog.models import Process, SystemCpu, SystemMemory
from reshog.render import render_table

WINDOW_SERVER = (
    "/System/Library/PrivateFrameworks/SkyLight.framework/Resources/WindowServer -daemon"
)
SPOTLIGHT_SUPPORT = (
    "/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/"
    "Metadata.framework/Versions/A/Support"
)
MDS_STORES = f"{SPOTLIGHT_SUPPORT}/mds_stores"
VM = (
    "/System/Library/Frameworks/Virtualization.framework/Versions/A/XPCServices/"
    "com.apple.Virtualization.VirtualMachine.xpc/Contents/MacOS/com.apple.Virtualization.VirtualMachine"
)
# 2026-10-12 に cpuhog の 1 位に出た(CPU 36〜80%)。
XPROTECT = (
    "/System/Library/PrivateFrameworks/XprotectFramework.framework/Versions/A/XPCServices/"
    "XprotectService.xpc/Contents/MacOS/XprotectService"
)


class TestDescribe:
    @pytest.mark.parametrize(
        ("command", "word"),
        [
            (WINDOW_SERVER, "画面"),
            ("/sbin/launchd", "親"),
            (MDS_STORES, "Spotlight"),
            (VM, "仮想マシン"),
            (XPROTECT, "マルウェア"),
        ],
    )
    def test_known(self, command: str, word: str) -> None:
        found = known.describe(command)
        assert found is not None and word in found.purpose

    def test_window_server_must_not_be_stopped(self) -> None:
        found = known.describe(WINDOW_SERVER)
        assert found is not None and not found.stoppable
        assert "ログアウト" in found.advice

    def test_spotlight_may_be_stopped_but_comes_back(self) -> None:
        """止めても害は無いが、すぐ起動し直す。「止めない」と矛盾した表示にしない。"""
        found = known.describe(MDS_STORES)
        assert found is not None and found.stoppable
        assert "起動し直す" in found.advice

    def test_spotlight_processes_have_distinct_purposes(self) -> None:
        """mds と mds_stores が同じ説明だと「索引づくりが 2 つ動いている」と読まれる。

        2026-10-24 に「なぜ 2 つ動いている？」と聞かれた。

        役割の違う組なので、それぞれの役割を書き分ける。対処(止めてもすぐ起動し直す)は共通。
        """
        names = ("mds", "mds_stores", "mdworker_shared")
        found = [known.describe(f"{SPOTLIGHT_SUPPORT}/{name}") for name in names]
        assert all(f is not None for f in found)
        purposes = [f.purpose for f in found if f is not None]
        assert len(set(purposes)) == len(names), purposes
        for f in found:
            assert f is not None and "Spotlight" in f.purpose and f.stoppable
            assert "起動し直す" in f.advice

    def test_vm_is_stopped_from_its_app(self) -> None:
        found = known.describe(VM)
        assert found is not None and found.stoppable
        assert "Docker" in found.advice

    def test_xprotect_points_to_developer_tools_not_kill(self) -> None:
        """kill してもすぐ起動し直す。減らす手はデベロッパツールへの登録と起動し直し。"""
        found = known.describe(XPROTECT)
        assert found is not None and not found.stoppable
        for word in ("起動し直す", "デベロッパツール", "署名"):
            assert word in found.advice, word

    def test_xprotect_advice_tells_how_to_confirm(self) -> None:
        """効いたかを利用者が自分で確かめられるよう、確認のコマンドを添える。"""
        found = known.describe(XPROTECT)
        assert found is not None and "Putting executable into provenance" in found.advice

    @pytest.mark.parametrize(
        "command",
        [
            "/opt/homebrew/bin/llama-server --port 8090",
            # 名前の一部が一致するだけのものを拾わない(実行ファイル名で比べる)
            "/usr/local/bin/my-WindowServer-tool",
            "python WindowServer.py",
            # OS の置き場所の外にある同名のファイルは別物
            "/tmp/mds",
            "/Users/me/bin/launchd",
            "",
        ],
    )
    def test_unknown(self, command: str) -> None:
        assert known.describe(command) is None


_SYSTEM = SystemMemory(phys=None, swap=None, free_percentage=None)
_CPU = SystemCpu(load_average=None, usage=None)


def _proc(pid: int, command: str) -> Process:
    return Process(pid=pid, mem_mb=900, rss_mb=900, cpu=0.0, command=command)


def _render(p: Process) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, width=250, no_color=True, highlight=False)
    render_table(console, [p], _SYSTEM, _CPU)
    return buffer.getvalue()


class TestTable:
    def test_command_cell_says_what_it_is(self, cell) -> None:
        out = _render(_proc(172, WINDOW_SERVER))
        assert "ⓘ" in cell(out, 172, "COMMAND")
        assert "止めない" in cell(out, 172, "COMMAND"), "止めてはいけないことも行に出す"

    def test_spotlight_row_does_not_say_do_not_stop(self, cell) -> None:
        cmd = cell(_render(_proc(316, MDS_STORES)), 316, "COMMAND")
        assert "Spotlight" in cmd and "止めない" not in cmd

    def test_xprotect_row_says_do_not_stop_and_footer_has_no_kill(self, cell) -> None:
        out = _render(_proc(51166, XPROTECT))
        assert "止めない" in cell(out, 51166, "COMMAND")
        assert "デベロッパツール" in out
        assert "kill 51166" not in out

    def test_stoppable_one_does_not_say_do_not_stop(self, cell) -> None:
        assert "止めない" not in cell(_render(_proc(700, VM)), 700, "COMMAND")

    def test_footer_explains_and_does_not_suggest_kill(self) -> None:
        out = _render(_proc(172, WINDOW_SERVER))
        assert "画面" in out and "ログアウト" in out
        assert "kill 172" not in out
        assert "停止するなら" not in out

    def test_stoppable_known_process_keeps_the_stop_hint(self) -> None:
        out = _render(_proc(700, VM))
        assert "仮想マシン" in out and "停止するなら" in out

    def test_unknown_process_is_unchanged(self, cell) -> None:
        out = _render(_proc(9, "/opt/homebrew/bin/llama-server"))
        assert "ⓘ" not in cell(out, 9, "COMMAND")
        assert "kill 9" in out


class TestKill:
    def _run(self, monkeypatch: pytest.MonkeyPatch, target: Process) -> tuple[str, list[int]]:
        sent: list[int] = []
        monkeypatch.setattr(typer, "prompt", lambda *a, **k: target.pid)
        monkeypatch.setattr(typer, "confirm", lambda *a, **k: True)
        monkeypatch.setattr(control, "current_pid", lambda: 1)
        monkeypatch.setattr(control, "send_signal", lambda pid, sig: sent.append(pid) or "ok")
        buffer = io.StringIO()
        cli._kill_process(
            [target], Console(file=buffer, width=200, no_color=True), force=False, assume_yes=False
        )
        return buffer.getvalue(), sent

    def test_unstoppable_gets_a_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        out, sent = self._run(monkeypatch, _proc(172, WINDOW_SERVER))
        assert "ログアウト" in out
        assert sent == [172], "警告しても、利用者が確認したら送る(止める手段を奪わない)"

    def test_stoppable_known_process_gets_no_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        out, sent = self._run(monkeypatch, _proc(700, VM))
        assert "ログアウト" not in out and "止めない" not in out
        assert sent == [700]

    def test_plain_process_gets_no_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        out, _ = self._run(monkeypatch, _proc(9, "/opt/homebrew/bin/llama-server"))
        assert "ログアウト" not in out
