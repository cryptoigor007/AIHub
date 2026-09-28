"""Unit tests for chat_meta (pins / archive / titles)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.common import chat_meta


@pytest.fixture(autouse=True)
def _tmp_data(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    chat_meta.set_data_dir(data)
    yield data
    chat_meta.set_data_dir(None)


def test_load_empty():
    assert chat_meta.load_meta() == {"pinned": [], "archived": [], "titles": {}}


def test_set_title():
    chat_meta.set_title("a1", "  Привет мир  ")
    assert chat_meta.load_meta()["titles"]["a1"] == "Привет мир"


def test_set_title_clear():
    chat_meta.set_title("a1", "X")
    chat_meta.set_title("a1", "")
    assert "a1" not in chat_meta.load_meta()["titles"]


def test_pin_unpin():
    chat_meta.toggle_pin("x", True)
    assert "x" in chat_meta.load_meta()["pinned"]
    chat_meta.toggle_pin("x", False)
    assert "x" not in chat_meta.load_meta()["pinned"]


def test_pin_toggle():
    chat_meta.toggle_pin("y")
    assert "y" in chat_meta.load_meta()["pinned"]
    chat_meta.toggle_pin("y")
    assert "y" not in chat_meta.load_meta()["pinned"]


def test_archive_unpins():
    chat_meta.toggle_pin("z", True)
    chat_meta.toggle_archive("z", True)
    m = chat_meta.load_meta()
    assert "z" in m["archived"]
    assert "z" not in m["pinned"]


def test_persist_roundtrip():
    chat_meta.set_title("id1", "Имя")
    chat_meta.toggle_pin("id1", True)
    path = chat_meta._path()
    assert path.exists()
    raw = json.loads(path.read_text())
    assert raw["titles"]["id1"] == "Имя"
    assert "id1" in raw["pinned"]
