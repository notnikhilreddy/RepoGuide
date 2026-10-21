from pathlib import Path

from repoguide.parser import parse_python_file, split_lines


def test_extracts_functions_and_methods(tmp_path: Path):
    file = tmp_path / "example.py"

    file.write_text(
        """
class UserService:
    def create_user(self, name):
        return {"name": name}

def create_app():
    return "app"
""".strip(),
        encoding="utf-8",
    )

    chunks = parse_python_file(file, tmp_path)

    symbols = {chunk.symbol_name for chunk in chunks}

    assert "UserService.create_user" in symbols
    assert "create_app" in symbols


def test_preserves_line_numbers(tmp_path: Path):
    file = tmp_path / "example.py"
    file.write_text(
        "x = 1\n\ndef answer():\n    return 42\n",
        encoding="utf-8",
    )

    chunks = parse_python_file(file, tmp_path)

    function = next(chunk for chunk in chunks if chunk.symbol_name == "answer")

    assert function.start_line == 3
    assert function.end_line == 4


def test_long_chunks_have_overlap():
    lines = [f"line {i}" for i in range(1, 121)]

    chunks = split_lines(
        lines,
        file_path="example.py",
        symbol_name="long_function",
        kind="function",
        start_line=1,
    )

    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 60
    assert chunks[1].start_line == 56
