"""control モジュール(プロセス停止)の単体テスト。

os.kill を monkeypatch し、停止の副作用を control に閉じたことで例外→結果コードの
翻訳がテストできることを確認する。
"""

import signal

import pytest

from reshog import control


class TestSendSignal:
    def test_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sent: list[tuple[int, int]] = []
        monkeypatch.setattr(control.os, "kill", lambda pid, sig: sent.append((pid, sig)))
        assert control.send_signal(4321, signal.SIGTERM) == "ok"
        assert sent == [(4321, signal.SIGTERM)]

    def test_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(pid: int, sig: int) -> None:
            raise ProcessLookupError

        monkeypatch.setattr(control.os, "kill", _raise)
        assert control.send_signal(4321, signal.SIGKILL) == "not_found"

    def test_denied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(pid: int, sig: int) -> None:
            raise PermissionError

        monkeypatch.setattr(control.os, "kill", _raise)
        assert control.send_signal(4321, signal.SIGTERM) == "denied"


class TestCurrentPid:
    def test_returns_own_pid(self) -> None:
        import os

        assert control.current_pid() == os.getpid()
