from pydantic import BaseModel, Field


class FileReadResponse(BaseModel):
    path: str
    content: str
    line_count: int
    hash: str


class FileWriteRequest(BaseModel):
    content: str


class FileCreateRequest(BaseModel):
    path: str = Field(min_length=1)
    content: str = ""
    is_directory: bool = False


class FileRenameRequest(BaseModel):
    new_path: str = Field(min_length=1)


class TreeNode(BaseModel):
    name: str
    path: str
    type: str
    size: int | None = None
    children: list["TreeNode"] | None = None


TreeNode.model_rebuild()
