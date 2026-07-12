"""Task 1: the package imports and exposes a version."""

import crew_fusebox


def test_package_imports():
    assert crew_fusebox is not None


def test_version_is_a_string():
    assert isinstance(crew_fusebox.__version__, str)
    assert crew_fusebox.__version__
