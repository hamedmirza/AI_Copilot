from app.services.token_estimator import (
    count_text_tokens,
    fit_messages_to_token_budget,
    get_encoding,
    truncate_text_to_tokens,
)


def test_count_text_tokens_uses_tiktoken():
    encoding = get_encoding()
    text = "hello world"
    assert count_text_tokens(text) == len(encoding.encode(text))
    assert count_text_tokens("") == 0


def test_truncate_text_to_tokens_respects_budget():
    encoding = get_encoding()
    text = "word " * 500
    truncated = truncate_text_to_tokens(text, 40)
    assert len(encoding.encode(truncated)) <= 40
    assert truncated.endswith("[truncated for context budget]")


def test_fit_messages_keeps_system_and_newest_history():
    system = {"role": "system", "content": "You are helpful."}
    old = {"role": "user", "content": "old " * 2000}
    recent = {"role": "user", "content": "recent question"}
    fitted, prompt_tokens, dropped = fit_messages_to_token_budget(
        [system, old, recent],
        max_context_tokens=800,
        reserve_output_tokens=200,
        tool_schemas=[],
    )
    assert fitted[0]["role"] == "system"
    assert _contains(fitted, recent)
    assert dropped >= 1
    assert prompt_tokens <= 800


def test_fit_messages_always_keeps_latest_user():
    system = {"role": "system", "content": "x" * 200}
    first = {"role": "user", "content": "first"}
    middle = {"role": "assistant", "content": "y" * 3000}
    latest = {"role": "user", "content": "latest user question"}
    fitted, _, dropped = fit_messages_to_token_budget(
        [system, first, middle, latest],
        max_context_tokens=600,
        reserve_output_tokens=100,
        tool_schemas=[],
    )
    assert _contains(fitted, latest)
    assert dropped >= 1


def test_fit_messages_recounts_with_tools():
    system = {"role": "system", "content": "sys"}
    user = {"role": "user", "content": "hi"}
    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]
    fitted, prompt_tokens, dropped = fit_messages_to_token_budget(
        [system, user],
        max_context_tokens=4096,
        reserve_output_tokens=512,
        tool_schemas=tools,
    )
    assert dropped == 0
    assert len(fitted) == 2
    assert prompt_tokens > count_text_tokens("hi")


def _contains(messages: list[dict], target: dict) -> bool:
    key = (target.get("role"), target.get("content"))
    return any((message.get("role"), message.get("content")) == key for message in messages)


def test_list_recent_messages_returns_tail(tmp_path):
    from app.db.models import ChatMessageModel, ChatSessionModel
    from app.db.session import SessionLocal
    from app.schemas.api import ProjectCreate
    from app.services.chat_service import ChatService
    from app.services.project_service import ProjectService

    project_dir = tmp_path / "tail-project"
    project_dir.mkdir()
    db = SessionLocal()
    try:
        project = ProjectService(db).create(
            ProjectCreate(
                name="tail",
                source_repo_spec=str(project_dir),
                validation_profile="python",
            )
        )
        session = ChatSessionModel(project_id=project.id, title="Tail", mode="general")
        db.add(session)
        db.commit()
        db.refresh(session)

        for index in range(5):
            db.add(
                ChatMessageModel(
                    session_id=session.id,
                    role="user",
                    content=f"message-{index}",
                )
            )
        db.commit()

        recent = ChatService(db).list_recent_messages(session.id, limit=2)
        assert [item.content for item in recent] == ["message-3", "message-4"]
    finally:
        db.close()
