"""group モジュール(アプリ単位の集約)の単体テスト。"""

import pytest

from reshog.group import app_label, group_label, group_processes
from reshog.models import Process, PsEntry


def _entry(pid: int, ppid: int, command: str) -> PsEntry:
    return PsEntry(pid=pid, ppid=ppid, rss_mb=0, command=command)


def _proc(pid: int, mem_mb: int, command: str = "x", rss_mb: int = 0) -> Process:
    return Process(pid=pid, mem_mb=mem_mb, rss_mb=rss_mb, cpu=0.0, command=command)


class TestAppLabel:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            (
                "/Applications/Google Chrome.app/Contents/Frameworks/"
                "Google Chrome Framework.framework/Helpers/Google Chrome Helper",
                "Google Chrome",
            ),
            ("/opt/homebrew/bin/llama-server -hf unsloth/Qwen3", "llama-server"),
            ("node /Users/x/.npm/_npx/abc/node_modules/.bin/playwright-mcp", "playwright-mcp"),
            ("/usr/bin/python main.py --port 8188", "main.py"),
            ("/usr/bin/python3 -m uvicorn tokyocal.web:app", "uvicorn"),
            # -c / -e の次はコードで、スクリプト名ではない(「import」と出ていた)。
            ("/usr/bin/python3 -u -c import sys;exec(eval(x))", "python3 -c"),
            ("node -e console.log(1)", "node -e"),
            ("", "?"),
        ],
    )
    def test_label(self, command: str, expected: str) -> None:
        assert app_label(command) == expected

    def test_interpreter_bundle_is_not_the_app_name(self) -> None:
        """Python.app は「入れ物」なので、動かしているスクリプト名を採る。"""
        command = (
            "/Users/x/.pyenv/versions/3.11.15/Library/Frameworks/Python.framework/"
            "Versions/3.11/Resources/Python.app/Contents/MacOS/Python "
            "/Users/x/.local/bin/koekaki menubar"
        )
        assert app_label(command) == "koekaki"


class TestGroupLabel:
    def test_helper_is_attributed_to_its_parent_app(self) -> None:
        """Chromium ヘルパーは、起動元の ixBrowser 側に寄せる。"""
        snapshot = {
            1: _entry(1, 0, "/sbin/launchd"),
            10: _entry(10, 1, "/Applications/ixBrowser.app/Contents/MacOS/ixBrowser"),
            11: _entry(11, 10, "/Users/x/Library/Application Support/ixBrowser-Resources/"
                                "chrome/142/Chromium.app/Contents/MacOS/Chromium"),
            12: _entry(12, 11, "/Users/x/Library/Application Support/ixBrowser-Resources/"
                                "chrome/142/Chromium.app/Contents/MacOS/Chromium --type=renderer"),
        }
        assert group_label(12, snapshot) == "ixBrowser"
        assert group_label(10, snapshot) == "ixBrowser"

    def test_shell_and_multiplexer_do_not_absorb_children(self) -> None:
        """tmux / zsh は「器」なので、そこで止めず配下のコマンド名を採る。"""
        snapshot = {
            1: _entry(1, 0, "/sbin/launchd"),
            20: _entry(20, 1, "tmux new-session"),
            21: _entry(21, 20, "-zsh"),
            22: _entry(22, 21, "/Users/x/.local/bin/claude --resume"),
        }
        assert group_label(22, snapshot) == "claude"

    def test_all_transparent_ancestors_falls_back_to_itself(self) -> None:
        """祖先が器ばかりなら、そのシェル自身が 1 グループになる(アイドルな shell 群)。"""
        snapshot = {
            1: _entry(1, 0, "/sbin/launchd"),
            20: _entry(20, 1, "tmux new-session"),
            21: _entry(21, 20, "-zsh"),
        }
        assert group_label(21, snapshot) == "zsh"

    def test_unknown_pid(self) -> None:
        assert group_label(999, {}) == "?"

    def test_cycle_does_not_hang(self) -> None:
        snapshot = {5: _entry(5, 6, "a"), 6: _entry(6, 5, "b")}
        assert group_label(5, snapshot) in {"a", "b"}


class TestGroupProcesses:
    @pytest.fixture
    def snapshot(self) -> dict[int, PsEntry]:
        return {
            1: _entry(1, 0, "/sbin/launchd"),
            10: _entry(10, 1, "/Applications/ixBrowser.app/Contents/MacOS/ixBrowser"),
            11: _entry(11, 10, "/Applications/ixBrowser.app/Contents/MacOS/Chromium"),
            12: _entry(12, 10, "/Applications/ixBrowser.app/Contents/MacOS/Chromium"),
            30: _entry(30, 1, "/opt/homebrew/bin/llama-server"),
        }

    def test_aggregates_and_sorts(self, snapshot: dict[int, PsEntry]) -> None:
        groups = group_processes(
            [_proc(30, 5000), _proc(10, 1000), _proc(11, 3000), _proc(12, 2000)], snapshot
        )
        assert [(g.label, g.total_mb, g.count) for g in groups] == [
            ("ixBrowser", 6000, 3),
            ("llama-server", 5000, 1),
        ]

    def test_distributed_app_outranks_a_bigger_single_process(
        self, snapshot: dict[int, PsEntry]
    ) -> None:
        """分散したアプリの合計が、単体最大のプロセスを上回るケース(本機能の存在理由)。"""
        groups = group_processes(
            [_proc(30, 5000), _proc(10, 2000), _proc(11, 2000), _proc(12, 2000)], snapshot
        )
        assert groups[0].label == "ixBrowser"
        assert groups[0].largest.mem_mb < 5000

    def test_largest_is_the_biggest_member(self, snapshot: dict[int, PsEntry]) -> None:
        groups = group_processes([_proc(11, 100), _proc(12, 900)], snapshot)
        assert groups[0].largest.pid == 12

    def test_hidden_gpu_propagates(self, snapshot: dict[int, PsEntry]) -> None:
        groups = group_processes(
            [_proc(11, 100), _proc(12, 3000, rss_mb=10)], snapshot
        )
        assert groups[0].hidden_gpu is True

    def test_empty(self) -> None:
        assert group_processes([], {}) == []
