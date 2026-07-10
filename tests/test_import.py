"""Task 1: the package imports and exposes a version."""

import agent_breaker


def test_package_imports():
    assert agent_breaker is not None


def test_version_is_a_string():
    assert isinstance(agent_breaker.__version__, str)
    assert agent_breaker.__version__
