from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import drain

NOW = datetime(2026, 7, 24, tzinfo=timezone.utc)
FIXTURES = os.path.join(os.path.dirname(drain.__file__), "fixtures")


def now() -> datetime:
    return NOW


def load_fixture(name: str) -> List[Dict[str, Any]]:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)
