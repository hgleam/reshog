"""プロセスの由来(どのプロジェクトから動いているか)を判定する。

材料は作業ディレクトリと launchd のジョブ名。どちらも collect が取り、ここでは
「リポのどこか」から「リポ名」へ寄せる判定だけを持つ(ファイルシステムの読み取りのみ)。
"""

from pathlib import Path

from .models import Origin

# GUI アプリを起動したときに launchd が自動で付けるラベル(末尾に乱数が付く)。
# COMMAND 列と同じことしか言わないので、由来としては出さない。
_GUI_APP_LABEL_PREFIX = "application."


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
    if launchd_label and not launchd_label.startswith(_GUI_APP_LABEL_PREFIX):
        return Origin(kind="launchd", name=launchd_label)
    return None
