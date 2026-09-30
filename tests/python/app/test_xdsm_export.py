import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from gemseo_process_builder.app.xdsm_export import SCRIPTS
from gemseo_process_builder.app.xdsm_export import inline_module
from gemseo_process_builder.app.xdsm_export import standalone_html

DIAGRAMS = {
    "root": {
        "nodes": [{"id": "Opt", "name": "Optimizer", "type": "optimization"}],
        "edges": [{"from": "_U_", "to": "Opt", "name": "x^(0)"}],
        "workflow": ["_U_", ["Opt"]],
        "optpb": "</script> is escaped",
    }
}


def test_modules_are_joined_without_imports_and_exports() -> None:
    module = inline_module(
        [
            "export const A = 1;\nexport function f() {\n  return A;\n}\n",
            'import { A, f } from "./a.js";\nimport {\n  B,\n} from "./b.js";\n'
            "export function g() {\n  return f() + A;\n}\n",
        ]
    )
    assert "import" not in module
    assert "export" not in module
    assert "function g()" in module


def test_page_inlines_everything() -> None:
    page = standalone_html(DIAGRAMS, "Sellar: Optimizer")
    assert "<title>Sellar: Optimizer</title>" in page
    assert "mountXdsm(document.getElementById" in page
    assert not re.search(r"^\s*import\s", page, re.MULTILINE)
    assert 'src="' not in page and "href=" not in page  # Nothing to download.
    data = re.search(r'id="xdsm-data">(.*?)</script>', page, re.DOTALL)
    assert data is not None
    assert json.loads(data.group(1)) == DIAGRAMS


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_inlined_renderer_is_valid_javascript(tmp_path: Path) -> None:
    root = Path(__file__).parents[3] / "gemseo_process_builder" / "static"
    module = inline_module(
        [(root / name).read_text(encoding="utf-8") for name in SCRIPTS]
    )
    path = tmp_path / "xdsm.mjs"
    path.write_text(module, encoding="utf-8")
    result = subprocess.run(
        ["node", "--check", str(path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
