"""Load unchanged native airline modules without the model runner entry point."""
from __future__ import annotations

import importlib.abc
import importlib.machinery
import os
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor/tau2-bench"
_metadata = None


class NoModelImports(importlib.abc.MetaPathFinder):
    """Make accidental provider/runner imports fail before initialization."""

    def find_spec(self, fullname, path=None, target=None):
        blocked = ("openai", "anthropic", "litellm", "tau2.registry", "tau2.runner",
                   "tau2.agent", "tau2.user", "tau2.utils.llm_utils")
        if any(fullname == name or fullname.startswith(name + ".") for name in blocked):
            _metadata["blocked_provider_imports"].append(fullname)
            raise ImportError(f"No-model pilot blocks {fullname}")
        return None


def install():
    """Install process-local guards and expose only native package submodules."""
    global _metadata
    if _metadata is not None:
        return _metadata
    if "tau2" in sys.modules:
        raise RuntimeError("Run bootstrap before any tau2 import")
    _metadata = {
        "upstream_commit": "2174a603f6d014ef94473ffa95957f6ce27100db",
        "root_package_initializer_executed": False,
        "skipped_eager_initializers": ["tau2", "tau2.voice.audio_native.openai"],
        "native_domain_and_evaluator_sources_modified": False,
        "dotenv_loading_disabled": True,
        "network_denied": True,
        "blocked_provider_imports": [], "blocked_network_attempts": [],
        "blocked_env_file_reads": [],
        "scope": "Native domain tools and direct native evaluator components; not official dialogue runner",
    }
    os.environ["TAU2_DATA_DIR"] = str(VENDOR / "data")
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    # Remove inherited provider secrets without inspecting or printing values.
    for name in list(os.environ):
        if name.endswith(("_API_KEY", "_ACCESS_TOKEN", "_SECRET_KEY")):
            os.environ.pop(name, None)
    import dotenv
    dotenv.load_dotenv = lambda *args, **kwargs: False

    def audit(event, args):
        if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.sendto"}:
            _metadata["blocked_network_attempts"].append(event)
            raise RuntimeError("Network disabled in no-model airline pilot")
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            filename = Path(os.fsdecode(args[0])).name.lower()
            if filename == ".env":
                _metadata["blocked_env_file_reads"].append(".env")
                raise RuntimeError("Credential file access disabled")

    sys.addaudithook(audit)
    sys.meta_path.insert(0, NoModelImports())
    package = types.ModuleType("tau2")
    package.__path__ = [str(VENDOR / "src/tau2")]
    package.__package__ = "tau2"
    package.__spec__ = importlib.machinery.ModuleSpec("tau2", loader=None, is_package=True)
    sys.modules["tau2"] = package
    # SimulationRun imports a pure LiveConfig schema under the voice package.
    # Its __init__ eagerly loads a live provider; only that re-export initializer
    # is bypassed, while the original live_config.py schema executes unchanged.
    voice_name = "tau2.voice.audio_native.openai"
    voice_package = types.ModuleType(voice_name)
    voice_package.__path__ = [str(VENDOR / "src/tau2/voice/audio_native/openai")]
    voice_package.__package__ = voice_name
    voice_package.__spec__ = importlib.machinery.ModuleSpec(voice_name, loader=None, is_package=True)
    sys.modules[voice_name] = voice_package
    return _metadata
