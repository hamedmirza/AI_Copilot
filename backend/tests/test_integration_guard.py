
from app.services.integration_guard import integration_guard_issues
from app.tools.lint_runner import normalize_tester_dry_run_commands


def test_orphan_kanban_page_blocks(tmp_path):
    pages = tmp_path / "frontend" / "src" / "pages"
    pages.mkdir(parents=True)
    (pages / "KanbanPage.tsx").write_text(
        "export default function KanbanPage() { return <div>Kanban</div> }\n",
        encoding="utf-8",
    )
    (tmp_path / "frontend" / "src" / "App.tsx").write_text(
        "export default function App() { return null }\n",
        encoding="utf-8",
    )
    issues = integration_guard_issues(tmp_path, changed_files=["frontend/src/pages/KanbanPage.tsx"])
    assert issues
    assert any("KanbanPage" in (i.get("message") or "") for i in issues)


def test_kanban_wired_in_workbench_passes(tmp_path):
    pages = tmp_path / "frontend" / "src" / "pages"
    workbench = tmp_path / "frontend" / "src" / "workbench"
    pages.mkdir(parents=True)
    workbench.mkdir(parents=True)
    (pages / "KanbanPage.tsx").write_text("export default function KanbanPage() {}\n", encoding="utf-8")
    (workbench / "builtins.tsx").write_text(
        "import KanbanPage from '@/pages/KanbanPage'\n"
        "import { KanbanWorkbenchPanel } from '@/components/Kanban/KanbanWorkbenchPanel'\n",
        encoding="utf-8",
    )
    issues = integration_guard_issues(tmp_path, changed_files=["frontend/src/pages/KanbanPage.tsx"])
    assert not [i for i in issues if i.get("severity") == "critical"]


def test_center_panel_not_mounted_in_app_fails(tmp_path):
    workbench = tmp_path / "frontend" / "src" / "workbench"
    workbench.mkdir(parents=True)
    (workbench / "builtins.tsx").write_text(
        "\n".join(
            [
                "import { KanbanWorkbenchPanel } from '@/components/Kanban/KanbanWorkbenchPanel'",
                "registerContribution({",
                "  id: 'kanban',",
                "  zone: 'center',",
                "  title: 'Kanban',",
                "  Component: KanbanWorkbenchPanel,",
                "})",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "frontend" / "src" / "App.tsx").write_text(
        "\n".join(
            [
                "export default function App() {",
                "  const BrowserComponent = null",
                "  return activeCenterView === 'browser' && BrowserComponent ? <BrowserComponent /> : null",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    issues = integration_guard_issues(tmp_path)
    assert any(
        "getContribution('center'" in (i.get("message") or "")
        or "CenterContent" in (i.get("message") or "")
        or "kanban" in (i.get("message") or "").lower()
        for i in issues
    )
    assert any(i.get("severity") == "critical" for i in issues)


def test_center_panel_mounted_via_get_contribution_passes(tmp_path):
    workbench = tmp_path / "frontend" / "src" / "workbench"
    workbench.mkdir(parents=True)
    (workbench / "builtins.tsx").write_text(
        "\n".join(
            [
                "import { KanbanWorkbenchPanel } from '@/components/Kanban/KanbanWorkbenchPanel'",
                "registerContribution({",
                "  id: 'kanban',",
                "  zone: 'center',",
                "  title: 'Kanban',",
                "  Component: KanbanWorkbenchPanel,",
                "})",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "frontend" / "src" / "App.tsx").write_text(
        "\n".join(
            [
                "import { getContribution } from '@/workbench/registry'",
                "function CenterContent() {",
                "  const contrib = getContribution('center', activeCenterView)",
                "  return contrib ? <contrib.Component /> : null",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    issues = integration_guard_issues(tmp_path)
    assert not [i for i in issues if "center panel" in (i.get("message") or "").lower()]
    assert not [i for i in issues if "getContribution('center'" in (i.get("message") or "")]


def test_normalize_tester_dry_run_uses_canonical_frontend_build():
    cmds = normalize_tester_dry_run_commands(
        ["tsc --noEmit", "npm run build"],
        ["frontend/src/App.tsx"],
    )
    assert cmds == ["npm --prefix frontend run build"]
