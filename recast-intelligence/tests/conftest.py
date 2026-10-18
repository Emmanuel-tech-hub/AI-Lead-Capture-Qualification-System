import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from recast_intel.config import load_config  # noqa: E402
from recast_intel.store import Store  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "RECAST_EMAIL_TO", "RECAST_EMAIL_FROM", "RECAST_SMTP_HOST",
              "RECAST_SMTP_USER", "RECAST_SMTP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    shutil.copy(ROOT / "config.yaml", tmp_path / "config.yaml")
    return load_config(root=tmp_path)


@pytest.fixture
def store(cfg):
    s = Store(cfg.db_path)
    yield s
    s.close()
