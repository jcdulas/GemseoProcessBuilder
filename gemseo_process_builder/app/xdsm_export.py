"""A standalone HTML page showing XDSM diagrams (SPEC § 13).

The page inlines d3, the XDSM renderer of the application and the diagrams:
it opens in any browser, without network access. The renderer and its layout
are ES modules of ``static/``; they are joined into one inline module by
removing their ``import`` lines and ``export`` keywords, which is enough since
the renderer only imports the layout.
"""

import html
import json
import re
from pathlib import Path
from typing import Any

from gemseo_process_builder.app.scheme_handler import STATIC_ROOT

SCRIPTS = ("js/lib/xdsm_layout.js", "js/views/xdsm/renderer.js")
"""The modules of the renderer, dependencies first."""

STYLES = ("css/tokens.css", "css/xdsm.css")
D3 = "vendor/d3.v7.min.js"

IMPORT_LINE = re.compile(r"^import\s.*?;\s*$", re.MULTILINE | re.DOTALL)
EXPORT_KEYWORD = re.compile(r"^export\s+", re.MULTILINE)

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
{styles}
html, body {{ height: 100%; margin: 0; }}
body {{ display: flex; flex-direction: column; font-family: var(--font-family);
  font-size: var(--font-size); color: var(--color-text);
  background: var(--color-background); }}
h1 {{ margin: 8px 12px; font-size: 16px; }}
#xdsm {{ display: flex; flex: 1; flex-direction: column; min-height: 0; }}
</style>
<script>{d3}</script>
</head>
<body>
<h1>{title}</h1>
<div id="xdsm"></div>
<script type="application/json" id="xdsm-data">{data}</script>
<script type="module">
{module}
const diagrams = JSON.parse(document.getElementById("xdsm-data").textContent);
mountXdsm(document.getElementById("xdsm"), diagrams);
</script>
</body>
</html>
"""


def inline_module(sources: list[str]) -> str:
    """Join ES modules into one, without their imports and export keywords."""
    return "\n".join(
        EXPORT_KEYWORD.sub("", IMPORT_LINE.sub("", source)) for source in sources
    )


def standalone_html(
    diagrams: dict[str, Any], title: str, static_root: Path = STATIC_ROOT
) -> str:
    """The HTML page showing XDSM diagrams, with everything inlined."""

    def read(name: str) -> str:
        return (static_root / name).read_text(encoding="utf-8")

    # "</" cannot appear inside a script element.
    data = json.dumps(diagrams).replace("</", "<\\/")
    return PAGE.format(
        title=html.escape(title),
        styles="\n".join(read(name) for name in STYLES),
        d3=read(D3),
        data=data,
        module=inline_module([read(name) for name in SCRIPTS]),
    )
