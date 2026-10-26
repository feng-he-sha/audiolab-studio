"""Export the model download manifest to MODELS.json (repo root).

This file is generated from ``audiolab.engines.registry`` so the GitHub repo has
a machine-readable download list without shipping model weights.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from audiolab.engines.registry import MODEL_SPECS  # noqa: E402


def main() -> int:
    payload = {
        "schema": 1,
        "note": "Model weights are not distributed with this repository. Download them with scripts/fetch_models.py or the Models page.",
        "models": [
            {
                "id": spec.id,
                "engine": spec.engine,
                "label": spec.label,
                "kind": spec.kind,
                "license": spec.license,
                "source": spec.source,
                "note": spec.note,
                "repo_id": spec.repo_id,
                "total_size": spec.total_size,
                "files": [
                    {
                        "filename": f.filename,
                        "size": f.size,
                        "sha256": f.sha256,
                        "subdir": f.subdir,
                        "url": f.url,
                    }
                    for f in spec.files
                ],
                "tags": spec.tags,
            }
            for spec in MODEL_SPECS
        ],
    }
    out = ROOT / "MODELS.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(payload['models'])} models)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
