from app.services.scope_guard import scope_issues


def test_scope_allows_blueprint_and_test_paths():
    blueprint = ["backend/app/services/foo.py", "frontend/src/App.tsx"]
    coder = ["backend/app/services/foo.py", "backend/tests/test_foo.py", "frontend/src/App.test.tsx"]
    issues = scope_issues(blueprint, coder, "implementation")
    assert issues == []


def test_scope_warns_on_unlisted_path():
    blueprint = ["backend/app/services/foo.py"]
    coder = ["backend/app/services/foo.py", "backend/app/services/bar.py"]
    issues = scope_issues(blueprint, coder, "implementation")
    assert len(issues) == 1
    assert issues[0]["source"] == "scope_guard"
    assert issues[0]["severity"] in {"suggestion", "important"}


def test_scope_flags_package_root_drift():
    blueprint = ["backend/app/services/foo.py"]
    coder = ["frontend/src/components/NewPanel.tsx"]
    issues = scope_issues(blueprint, coder, "implementation")
    assert any(issue["severity"] == "important" for issue in issues)


def test_scope_neighbor_is_lenient_suggestion():
    blueprint = ["backend/app/services/foo.py"]
    coder = ["backend/app/services/foo_helper.py"]
    issues = scope_issues(blueprint, coder, "implementation")
    assert len(issues) == 1
    assert issues[0]["severity"] == "suggestion"
    assert "neighbor" in issues[0]["message"].lower()
