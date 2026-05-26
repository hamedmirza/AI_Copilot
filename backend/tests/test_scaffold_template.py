from app.services.scaffold_template_service import ScaffoldTemplateService, default_scaffold_variables


def test_scaffold_lists_templates():
    svc = ScaffoldTemplateService()
    paths = svc.list_template_paths()
    assert "AGENTS.md" in paths
    assert "docs/VERIFICATION_RULES.md" in paths


def test_scaffold_renders_placeholders():
    svc = ScaffoldTemplateService()
    vars_ = default_scaffold_variables("Demo App", "A demo project", stack="python")
    rendered = svc.render("README.md", vars_)
    assert "Demo App" in rendered
    assert "{{PROJECT_NAME}}" not in rendered


def test_scaffold_context_block():
    block = ScaffoldTemplateService().build_context_block(default_scaffold_variables("X", "Y"))
    assert "Canonical scaffold template" in block
    assert "AGENTS.md" in block
