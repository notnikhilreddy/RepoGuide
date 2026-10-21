import pytest
from repoguide.docs_catalog import choose_docs, get_doc, should_use_docs


def test_docs_for_lifespan_migration():
    choices = choose_docs("How should we migrate FastAPI startup events to lifespan?")
    assert ("fastapi", "lifespan") in {(d.library, d.topic) for d in choices}
    assert should_use_docs("How should we migrate FastAPI startup events to lifespan?", "auto", choices)


def test_code_only_question_does_not_trigger_external_docs():
    q = "How does a repository indexing request reach the database?"
    assert not should_use_docs(q, "auto", choose_docs(q))


def test_never_disables_tools():
    q = "Read official FastAPI lifespan docs"
    assert not should_use_docs(q, "never", choose_docs(q))


def test_unknown_docs_rejected():
    with pytest.raises(ValueError):
        get_doc("unknown", "all")


def test_uses_bounded_catalog():
    assert len(choose_docs("FastAPI, SQLAlchemy, and Alembic migration docs")) <= 2
