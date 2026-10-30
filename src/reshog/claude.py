"""Claude Code のセッションを見分け、状態ファイルの場所を決める。

--project の行に「どのセッションを閉じてよいか(状態・経過)」と「どこを開けば閉じられるか(tmux)」を
添える。状態は Claude Code 自身が PID ごとに書く `<設定フォルダ>/sessions/<PID>.json` から読む。
会話ログ(jsonl)の更新時刻では推定しない: 同じ作業場所のセッションがログの置き場を共有し、
再開したセッションは別の ID のログへ書くので、他のセッションの時刻を拾う。
"""

from pathlib import Path

from .constants import CLAUDE_DEFAULT_DIR, CLAUDE_EXECUTABLE, CLAUDE_SESSIONS_DIR


def is_claude(command: str) -> bool:
    """Claude Code の本体のプロセスか(実行ファイル名が claude)。

    子の MCP サーバー・フックは別の実行ファイルなので当たらない。

    Args:
        command: フルコマンド文字列。

    Returns:
        Claude Code の本体なら True。
    """
    args = command.split()
    return bool(args) and args[0].rsplit("/", 1)[-1] == CLAUDE_EXECUTABLE


def session_file(config_dir: str | None, home: Path, pid: int) -> Path:
    """そのセッションの状態ファイルの場所。

    Args:
        config_dir: そのプロセスの CLAUDE_CONFIG_DIR。付けずに起動していれば None。
        home: ホームディレクトリ(既定の設定フォルダの親)。
        pid: プロセス ID。

    Returns:
        `<設定フォルダ>/sessions/<PID>.json`。
    """
    base = Path(config_dir) if config_dir else home / CLAUDE_DEFAULT_DIR
    return base / CLAUDE_SESSIONS_DIR / f"{pid}.json"
