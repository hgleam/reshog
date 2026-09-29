"""プロセスの由来(どのプロジェクトから動いているか)を判定する。

材料は作業ディレクトリと launchd のジョブ名。どちらも collect が取り、ここでは
「リポのどこか」から「リポ名」へ寄せる判定だけを持つ(ファイルシステムの読み取りのみ)。
"""

from pathlib import Path

from .constants import APPLE_LABEL_PREFIX, GUI_APP_LABEL_PREFIX
from .models import Origin


def repo_root(cwd: str) -> Path | None:
    """cwd を含む git リポの最上位ディレクトリを返す。

    worktree の `.git` はファイルで、`gitdir: <本体>/.git/worktrees/<名前>` を指す。
    置き場所に依存せず本体のリポへ寄せるため、パスの形ではなく gitdir を読む。

    Args:
        cwd: 作業ディレクトリ。

    Returns:
        リポの最上位。リポの外・存在しないディレクトリなら None。
    """
    start = Path(cwd)
    if not start.is_dir():
        return None
    for directory in (start, *start.parents):
        dot_git = directory / ".git"
        if dot_git.is_dir():
            return directory
        if dot_git.is_file():
            return _main_repo_of(directory, dot_git)
    return None


def _main_repo_of(directory: Path, dot_git: Path) -> Path:
    """`.git` がファイルのとき、worktree なら本体のリポを、それ以外なら自分を返す。

    Args:
        directory: `.git` ファイルを持つディレクトリ。
        dot_git: その `.git` ファイル。

    Returns:
        本体のリポ(worktree のとき)または directory 自身(submodule 等)。
    """
    try:
        content = dot_git.read_text(encoding="utf-8").strip()
    except OSError:
        return directory
    gitdir = content.removeprefix("gitdir:").strip()
    marker = "/.git/worktrees/"
    if marker in gitdir:
        return Path(gitdir.split(marker, 1)[0])
    return directory


def label(found: Origin) -> str:
    """PJ の表記。PJ 列と PJ 別の合計(--project)で共有する。

    リポ名とジョブ名は別物なので、ジョブ名には `launchd:` を付けて見分けられるようにする。

    Args:
        found: 判定済みの由来。

    Returns:
        表示名。
    """
    return f"launchd:{found.name}" if found.kind == "launchd" else found.name


def resolve(cwd: str | None, launchd_label: str | None) -> Origin | None:
    """作業ディレクトリと launchd のジョブ名から由来を決める。

    リポ名を優先する(同じリポの常駐ジョブも、手で起動したものも同じ名前で並ぶ)。
    リポの外で動く常駐ジョブ(cwd が `/` の launchd ジョブ等)はジョブ名で示す。

    Args:
        cwd: 作業ディレクトリ。取れなければ None。
        launchd_label: launchd のジョブ名。ジョブでなければ None。

    Returns:
        Origin。どちらからも分からなければ None。
    """
    root = repo_root(cwd) if cwd else None
    if root is not None:
        return Origin(kind="git", name=root.name)
    if launchd_label and not launchd_label.startswith(GUI_APP_LABEL_PREFIX):
        return Origin(kind="launchd", name=launchd_label)
    return None


def launchd_service(launchd_label: str | None, domain: str) -> str | None:
    """止めるときに launchctl bootout へ渡すサービス名(`<ドメイン>/<ラベル>`)。

    PJ 列とは別の事実。作業ディレクトリがリポの中でも、launchd のジョブなら kill しても
    起動し直されうる(KeepAlive)。止める案内はこの値で決める。

    Args:
        launchd_label: launchctl list のラベル。ジョブでなければ None。
        domain: そのラベルを読んだドメイン("gui/<uid>" または "system")。

    Returns:
        サービス名。ジョブでない・GUI アプリ・OS のエージェントなら None(kill を案内する)。
    """
    if not launchd_label or launchd_label.startswith((GUI_APP_LABEL_PREFIX, APPLE_LABEL_PREFIX)):
        return None
    return f"{domain}/{launchd_label}"
