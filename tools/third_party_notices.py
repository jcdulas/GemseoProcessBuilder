"""Write THIRD_PARTY_NOTICES.md from the installed dependencies (SPEC § 14.6).

Usage:
    python tools/third_party_notices.py

The runtime dependencies of the package are followed recursively in the
project's virtual environment; the license of each one comes from its metadata.
Licenses that are ambiguous or multiple are confirmed in ``CONFIRMED``, after
reading them. Run it after adding or upgrading a dependency, and check the
result: a license missing from ``ACCEPTED`` stops the script.
"""

import importlib.metadata as metadata
import sys
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "THIRD_PARTY_NOTICES.md"
PACKAGE = "gemseo-process-builder"

CONFIRMED = {
    "pyside6": "LGPL-3.0-only (used under its LGPL option)",
    "pyside6-addons": "LGPL-3.0-only (used under its LGPL option)",
    "pyside6-essentials": "LGPL-3.0-only (used under its LGPL option)",
    "shiboken6": "LGPL-3.0-only (used under its LGPL option)",
    "matplotlib": "Matplotlib License (PSF-based, permissive)",
    "python-dateutil": "Apache-2.0 OR BSD-3-Clause",
    "numpy": "BSD-3-Clause",
    "scipy": "BSD-3-Clause",
    "pandas": "BSD-3-Clause",
    "networkx": "BSD-3-Clause",
    "jinja2": "BSD-3-Clause",
    "kiwisolver": "BSD-3-Clause",
    "colorama": "BSD-3-Clause",
    "cycler": "BSD-3-Clause",
    "pint": "BSD-3-Clause",
    "sympy": "BSD-3-Clause",
    "mpmath": "BSD-3-Clause",
    "flexcache": "BSD-3-Clause",
    "fastjsonschema": "BSD-3-Clause",
    "xxhash": "BSD-2-Clause",
    "packaging": "Apache-2.0 OR BSD-2-Clause",
    "pyxdsm": "Apache-2.0",
    "xdsmjs": "Apache-2.0",
    "strenum": "MIT",
    "wcwidth": "MIT",
    # The wheel says MIT, but the compiled library includes the Luksan routines:
    # LGPL-2.1-or-later as a whole (its LICENSE file), used as an imported library.
    "nlopt": "LGPL-2.1-or-later (MIT, with LGPL Luksan routines)",
}
"""Licenses read and confirmed by hand, where the metadata is vague."""

ACCEPTED = (
    "MIT",
    "BSD",
    "Apache",
    "ISC",
    "PSF",
    "Matplotlib",
    "MPL-2.0",
    "LGPL-3.0",
)
"""License families compatible with distributing the project under MIT, as
imported dependencies (SPEC § 14.6); MPL-2.0 and LGPL only unmodified."""

VENDORED = [
    ("d3", "7.9.0", "ISC", "https://d3js.org"),
    (
        "elkjs",
        "0.12.0",
        "EPL-2.0 (dual EPL-2.0 / GPL-3.0-or-later upstream; used under EPL-2.0)",
        "https://github.com/kieler/elkjs",
    ),
    ("Inter (font)", "4.1", "OFL-1.1", "https://rsms.me/inter/"),
]
"""JavaScript and font files of ``static/vendor/`` (see its README.md)."""


def _requirements(name: str) -> list[str]:
    """The runtime requirements of an installed distribution."""
    distribution = metadata.distribution(name)
    names = []
    for text in distribution.requires or []:
        requirement = Requirement(text)
        if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
            continue
        names.append(requirement.name)
    return names


def _license(distribution: metadata.Distribution) -> str:
    fields = distribution.metadata
    text = fields.get("License-Expression") or fields.get("License") or ""
    if not text or len(text) > 60:
        classifiers = [
            item.split("::")[-1].strip()
            for item in fields.get_all("Classifier") or []
            if item.startswith("License")
        ]
        text = "; ".join(classifiers) or text[:60]
    return text


def dependencies() -> list[tuple[str, str, str, str]]:
    """Every runtime dependency: (name, version, license, home page)."""
    found: dict[str, tuple[str, str, str, str]] = {}
    pending = _requirements(PACKAGE)
    while pending:
        name = pending.pop()
        key = name.lower().replace("_", "-")
        if key in found:
            continue
        try:
            distribution = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue  # Not needed on this platform.
        fields = distribution.metadata
        urls = fields.get_all("Project-URL") or []
        home = fields.get("Home-page") or (
            urls[0].split(",")[-1].strip() if urls else ""
        )
        license_text = CONFIRMED.get(key, _license(distribution))
        found[key] = (key, distribution.version, license_text, home)
        pending.extend(_requirements(name))
    return [found[key] for key in sorted(found)]


def main() -> int:
    """Write the notices; fail on a license that is not accepted."""
    rows = dependencies()
    refused = [row for row in rows if not any(item in row[2] for item in ACCEPTED)]
    if refused:
        for name, version, license_text, _ in refused:
            print(f"Check the license of {name} {version}: {license_text!r}")
        return 1
    lines = [
        "# Third-party notices",
        "",
        "GEMSEO Process Builder is distributed under the MIT license (see",
        "[LICENSE](LICENSE)). It uses the following components under their own",
        "licenses, all compatible with this distribution (SPEC § 14.6): permissive",
        "licenses, and LGPL-3.0 or MPL-2.0 libraries used as unmodified imported",
        "dependencies.",
        "",
        "This file is written by `tools/third_party_notices.py`.",
        "",
        "## Vendored JavaScript and fonts",
        "",
        "Committed unmodified in `gemseo_process_builder/static/vendor/`, with their",
        "license texts in `static/vendor/LICENSES/`.",
        "",
        "| Component | Version | License | Home page |",
        "|---|---|---|---|",
        *(
            f"| {name} | {version} | {text} | {url} |"
            for name, version, text, url in VENDORED
        ),
        "",
        "## Python dependencies",
        "",
        "Installed by pip with the package (runtime dependencies, recursively).",
        "",
        "| Component | Version | License | Home page |",
        "|---|---|---|---|",
        *(
            f"| {name} | {version} | {text} | {url} |"
            for name, version, text, url in rows
        ),
        "",
    ]
    OUTPUT.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT.name}: {len(rows)} Python dependencies.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
