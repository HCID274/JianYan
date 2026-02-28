import sys
from unittest.mock import MagicMock

# Mock httpx before importing utils.updater because it's imported at the module level
mock_httpx = MagicMock()
sys.modules["httpx"] = mock_httpx

from utils.updater import is_newer_version

def test_is_newer_version_basic():
    assert is_newer_version("1.0.1", "1.0.0") is True
    assert is_newer_version("1.1.0", "1.0.0") is True
    assert is_newer_version("2.0.0", "1.0.0") is True
    assert is_newer_version("1.0.0", "1.0.0") is False
    assert is_newer_version("0.9.9", "1.0.0") is False

def test_is_newer_version_v_prefix():
    assert is_newer_version("v1.0.1", "1.0.0") is True
    assert is_newer_version("1.0.1", "v1.0.0") is True
    assert is_newer_version("v1.0.1", "v1.0.0") is True

def test_is_newer_version_varying_lengths():
    assert is_newer_version("1.1", "1.0.9") is True
    assert is_newer_version("1.0.1", "1.0") is True
    assert is_newer_version("1.1", "1.1.0") is False
    assert is_newer_version("1.0", "1.0.0") is False
    assert is_newer_version("1.0.0", "1.0") is False

def test_is_newer_version_whitespace():
    assert is_newer_version(" 1.0.1 ", "1.0.0") is True
    assert is_newer_version("1.0.1", " 1.0.0 ") is True

def test_is_newer_version_fallback_behavior():
    # Still should handle non-numeric strings using inequality
    assert is_newer_version("beta", "1.0.0") is True
    assert is_newer_version("1.0.0", "beta") is True
    assert is_newer_version("invalid", "invalid") is False
