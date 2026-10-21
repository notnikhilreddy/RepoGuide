from types import SimpleNamespace

import pytest

from repoguide.context import pack_context
from repoguide.hybrid import SearchHit, rrf_fuse, search


def hit(id_: str, file: str = "a.py", start: int = 1, end: int = 6):
    chunk = SimpleNamespace(
        id=id_,
        file_path=file,
        symbol_name=f"symbol_{id_}",
        start_line=start,
        end_line=end,
        content="\n".join(f"line {i}" for i in range(start, end + 1)),
    )
    return SearchHit(chunk=chunk, origin="dense", channels=("dense",))


def test_rrf_rewards_agreement():
    dense = [hit("a"), hit("b")]
    lexical = [hit("b"), hit("c")]
    fused = rrf_fuse([("dense", dense), ("keyword", lexical)])
    assert fused[0].chunk.id == "b"
    assert fused[0].channels == ("dense", "keyword")
    assert len({x.chunk.id for x in fused}) == 3
    assert fused[0].fusion_score > fused[1].fusion_score


def test_rrf_no_duplicate_credit_for_same_channel():
    fused = rrf_fuse([("dense", [hit("a"), hit("a"), hit("b")])])
    assert [x.chunk.id for x in fused] == ["a", "b"]
    assert fused[0].fusion_score == pytest.approx(1 / 61)
    assert fused[1].fusion_score == pytest.approx(1 / 62)


def test_context_skips_overlapping_window():
    entries = [
        hit("a", start=1, end=10),
        hit("b", start=3, end=8),  # entirely covered by first chunk
        hit("c", file="b.py", start=1, end=5),
    ]
    packed = pack_context(entries, max_chars=2000)
    assert [p.hit.chunk.id for p in packed] == ["a", "c"]


def test_context_caps_and_preserves_line_numbers():
    entry = hit("a", start=20, end=119)
    entry.chunk.content = "\n".join("some long line content" for _ in range(100))
    packed = pack_context([entry], max_chars=350, per_chunk_chars=175)
    assert len(packed) == 1
    assert 20 <= packed[0].end_line < 119
    assert len(packed[0].content) <= 175


def test_search_validates_mode_without_database():
    with pytest.raises(ValueError, match="Unknown retrieval mode"):
        search(session=None, repo_id="repo", question="why", retrieval_mode="nope")


def test_lexical_terms_filters_stopwords_and_operators():
    from repoguide.hybrid import lexical_terms

    assert (
        lexical_terms("Where is `authenticate_user()` defined?") == "authenticate_user"
    )
    assert (
        lexical_terms("Why call foo | drop; <script>?") == "call | foo | drop | script"
    )
