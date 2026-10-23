from repoguide.routing_v2 import plan, select_dependencies, assess_evidence


def test_repo_only():
    result = plan("How does indexing reach the database?", [{"file_path":"indexer.py","symbol_name":"index_repository"}], ["fastapi"])
    assert result.tools == []


def test_external_explicit_dependency():
    result = plan("How should I migrate FastAPI startup to lifespan?", [{"file_path":"main.py"}], ["fastapi"])
    assert "context7" in result.tools
    assert result.dependencies == ["fastapi"]


def test_explicit_never_is_hard_block():
    result = plan("Latest FastAPI migration on GitHub", [], ["fastapi"], "never")
    assert result.tools == []


def test_no_arbitrary_dependency():
    assert select_dependencies("Help with version migration", ["fastapi", "sqlalchemy"]) == []


def test_exact_package_boundaries():
    assert select_dependencies("How to use pytest?", ["test", "pytest"]) == ["pytest"]


def test_evidence_no_chunks():
    assert not assess_evidence("anything", []).sufficient
