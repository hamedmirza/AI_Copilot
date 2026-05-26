from __future__ import annotations

from pathlib import Path

import git
from git import Repo
from git.exc import GitCommandError

from app.core.exceptions import ValidationError


class GitService:
    def __init__(self, repo_path: Path) -> None:
        self.path = repo_path.resolve()
        if not (self.path / ".git").exists():
            Repo.init(self.path)
        self.repo = Repo(self.path)

    def _has_commits(self) -> bool:
        try:
            self.repo.head.commit
            return True
        except (ValueError, TypeError):
            return False

    def _default_remote(self) -> git.Remote | None:
        if not self.repo.remotes:
            return None
        try:
            return self.repo.remotes.origin
        except AttributeError:
            return self.repo.remotes[0]

    def status(self) -> dict:
        staged, unstaged, untracked = [], [], []
        for line in self.repo.git.status("--porcelain").splitlines():
            if len(line) < 4:
                continue
            index_status = line[0]
            worktree_status = line[1]
            path = line[3:].strip()
            if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
                path = bytes(path[1:-1], "utf-8").decode("unicode_escape")
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if index_status == "?" and worktree_status == "?":
                untracked.append({"path": path, "status": "?"})
            elif index_status not in (" ", "?"):
                staged.append({"path": path, "status": index_status})
            if worktree_status not in (" ", "?"):
                unstaged.append({"path": path, "status": worktree_status})
        ahead, behind = 0, 0
        branch = self.current_branch()
        if branch not in ("", "HEAD") and self._has_upstream(branch):
            try:
                counts = self.repo.git.rev_list("--left-right", "--count", f"{branch}@{{u}}...{branch}")
                behind_s, ahead_s = counts.split()
                behind, ahead = int(behind_s), int(ahead_s)
            except GitCommandError:
                pass
        return {
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
            "ahead": ahead,
            "behind": behind,
        }

    def stage(self, paths: list[str]) -> None:
        if not paths:
            return
        self.repo.index.add(paths)

    def stage_all(self) -> None:
        self.repo.git.add("-A")

    def unstage(self, paths: list[str]) -> None:
        if not paths:
            return
        self.repo.index.reset(paths, working_tree=True)

    def _index_has_commitable_changes(self) -> bool:
        if not self._has_commits():
            return bool(self.repo.index.entries)
        return bool(self.repo.index.diff("HEAD"))

    def commit(self, message: str, author_name: str, author_email: str) -> str:
        if not message.strip():
            raise ValidationError("Commit message required")
        self.stage_all()
        if not self._index_has_commitable_changes():
            raise ValidationError("No changes to commit")
        actor = git.Actor(author_name, author_email)
        try:
            commit = self.repo.index.commit(message, author=actor, committer=actor)
        except GitCommandError as exc:
            raise ValidationError(str(exc)) from exc
        return commit.hexsha

    def log(self, limit: int = 30) -> list[dict]:
        if not self._has_commits():
            return []
        commits = []
        for c in self.repo.iter_commits(max_count=limit):
            commits.append(
                {
                    "sha": c.hexsha[:8],
                    "message": c.message.strip(),
                    "author": str(c.author),
                    "date": c.committed_datetime.isoformat(),
                }
            )
        return commits

    def branches(self) -> list[str]:
        return [h.name for h in self.repo.heads]

    def current_branch(self) -> str:
        try:
            return self.repo.active_branch.name
        except TypeError:
            return "HEAD"

    def checkout(self, branch: str) -> None:
        try:
            self.repo.git.checkout(branch)
        except GitCommandError as exc:
            raise ValidationError(str(exc)) from exc

    def diff(self, path: str) -> dict:
        if self._has_commits():
            try:
                diff = self.repo.git.diff("HEAD", "--", path)
            except GitCommandError:
                diff = self.repo.git.diff("--", path)
        else:
            diff = self.repo.git.diff("--cached", "--", path) or self.repo.git.diff("--", path)
        original = ""
        if (self.path / path).exists():
            original = (self.path / path).read_text(encoding="utf-8")
        return {"path": path, "diff": diff, "original": original}

    def has_remote(self) -> bool:
        return self._default_remote() is not None

    def remote_name(self) -> str | None:
        remote = self._default_remote()
        return remote.name if remote else None

    def _has_upstream(self, branch: str) -> bool:
        try:
            self.repo.git.rev_parse("--verify", f"{branch}@{{u}}")
            return True
        except GitCommandError:
            return False

    def push(self) -> dict:
        remote = self._default_remote()
        if remote is None:
            raise ValidationError("No remote configured")
        branch = self.current_branch()
        if branch in ("", "HEAD"):
            raise ValidationError("Cannot push: not on a branch")
        try:
            if self._has_upstream(branch):
                self.repo.git.push(remote.name, branch)
            else:
                self.repo.git.push("-u", remote.name, branch)
        except GitCommandError as exc:
            raise ValidationError(str(exc)) from exc
        return {"remote": remote.name, "branch": branch}

    def pull(self) -> dict:
        remote = self._default_remote()
        if remote is None:
            raise ValidationError("No remote configured")
        branch = self.current_branch()
        if branch in ("", "HEAD"):
            raise ValidationError("Cannot pull: not on a branch")
        try:
            self.repo.git.pull(remote.name, branch)
        except GitCommandError as exc:
            raise ValidationError(str(exc)) from exc
        return {"remote": remote.name, "branch": branch}
