from pydantic import BaseModel, Field


class GitStatusResponse(BaseModel):
    branch: str
    staged: list[str]
    unstaged: list[str]
    untracked: list[str]
    has_remote: bool


class GitPathsRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)


class GitCommitRequest(BaseModel):
    message: str = Field(min_length=1)


class GitCheckoutRequest(BaseModel):
    branch: str = Field(min_length=1)


class GitLogEntry(BaseModel):
    sha: str
    message: str
    author: str
    date: str


class GitLogResponse(BaseModel):
    commits: list[GitLogEntry]


class GitBranchesResponse(BaseModel):
    current: str
    branches: list[str]
