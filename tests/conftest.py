import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def tags():
    """Tag list of a registry repository (or Helm chart versions), captured on 2026-10-24."""

    def read(name):
        return (FIXTURES / "tags" / f"{name}.txt").read_text(encoding="utf-8").split()

    return read
