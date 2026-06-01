from __future__ import annotations

from dataclasses import dataclass
from typing import Any


JsonDict = dict[str, Any]


@dataclass(slots=True)
class StageResult:
    stage_name: str
    output_path: str
    payload: JsonDict
