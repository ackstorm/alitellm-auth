# SPDX-License-Identifier: Apache-2.0
"""Boot-guard tests for the vendored LiteLLM custom auth (review fix #2).

auth_user_map.py runs on the LiteLLM proxy (not in this package) and imports
`litellm`. We stub those imports via sys.modules and load the file by path so the
import-time PROXY_MASTER_KEY guard can be exercised here.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_AUTH_MAP_PATH = Path(__file__).resolve().parents[3] / "deploy" / "litellm" / "auth_user_map.py"


def _install_litellm_stubs() -> None:
    litellm = types.ModuleType("litellm")
    proxy = types.ModuleType("litellm.proxy")
    types_mod = types.ModuleType("litellm.proxy._types")
    proxy.proxy_server = types.SimpleNamespace(prisma_client=None)

    class ProxyException(Exception):
        def __init__(self, *, message="", type="", param="", code=0):
            super().__init__(message)
            self.message, self.type, self.param, self.code = message, type, param, code

    class UserAPIKeyAuth:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    types_mod.ProxyException = ProxyException
    types_mod.UserAPIKeyAuth = UserAPIKeyAuth
    litellm.proxy = proxy
    sys.modules["litellm"] = litellm
    sys.modules["litellm.proxy"] = proxy
    sys.modules["litellm.proxy._types"] = types_mod


def _load_auth_map():
    _install_litellm_stubs()
    spec = importlib.util.spec_from_file_location("auth_user_map_uut", _AUTH_MAP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # runs the import-time guard
    return module


def test_import_succeeds_when_master_key_set(monkeypatch):
    monkeypatch.setenv("PROXY_MASTER_KEY", "sk-master-xyz")
    module = _load_auth_map()
    assert module.MASTER_KEY == "sk-master-xyz"


def test_import_fails_closed_when_master_key_unset(monkeypatch):
    monkeypatch.delenv("PROXY_MASTER_KEY", raising=False)
    with pytest.raises(RuntimeError, match="PROXY_MASTER_KEY"):
        _load_auth_map()
