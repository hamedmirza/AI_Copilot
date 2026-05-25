from __future__ import annotations

from pathlib import Path

import git
from git import Repo

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

    def status(self) -> dict:
        staged, unstaged, untracked = [], [], []
        for line in self.repo.git.status("--porcelain").splitlines():
            if len(line) < 4:
                continue
            index_status = line[0]
            worktree_status = line[1]
            path = line[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if index_status == "?" and worktree_status == "?":
                untracked.append({"path": path, "status": "?"})
            elif index_status not in (" ", "?"):
                staged.append({"path": path, "status": index_status})
            if worktree_status not in (" ", "?"):
                unstaged.append({"path": path, "status": worktree_status})
        return {"staged": staged, "unstaged": unstaged, "untracked": untracked}

    def stage(self, paths: list[str]) -> None:
        self.repo.index.add(paths)

    def unstage(self, paths: list[str]) -> None:
        self.repo.index.reset(paths, working_tree=True)

    def commit(self, message: str, author_name: str, author_email: str) -> str:
        if not message.strip():
            raise ValidationError("Commit message required")
        actor = git.Actor(author_name, author_email)
        commit = self.repo.index.commit(message, author=actor, committer=actor)
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
        self.repo.git.checkout(branch)

    def diff(self, path: str) -> dict:
        if self._has_commits():
            try:
                diff = self.repo.git.diff("HEAD", "--", path)
            except git.GitCommandError:
                diff = self.repo.git.diff("--", path)
        else:
            diff = self.repo.git.diff("--cached", "--", path) or self.repo.git.diff("--", path)
        original = ""
        if (self.path / path).exists():
            original = (self.path / path).read_text(encoding="utf-8")
        return {"path": path, "diff": diff, "original": original}

    def has_remote(self) -> bool:
        return bool(self.repo.remotes)

    def push(self) -> None:
        if not self.has_remote():
            raise ValidationError("No remote configured")
        self.repo.remotes.origin.push()

    def pull(self) -> None:
        if not self.has_remote():
            raise ValidationError("No remote configured")
        self.repo.remotes.origin.pull()
