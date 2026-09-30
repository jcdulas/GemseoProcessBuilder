"""Compare a pip freeze taken elsewhere with the pinned requirements.

Usage:
    python tools/requirements_diff.py <freeze-file>
    python -m pip freeze | python tools/requirements_diff.py -

The argument is a ``pip freeze`` (or ``pip list --format=freeze``) output taken
on the machine to compare with; ``-`` reads it from the standard input. The
reference is the pinned ``requirements.txt`` of this repository; entries coming
from a git URL are listed but not compared, since they carry no version.

Packages older on that machine are listed first: they are the ones the code has
to be adapted to. The report goes to the standard output and the exit code is
always 0, except when a file cannot be read.
"""

import re
import sys
from pathlib import Path

try:
    from packaging.version import InvalidVersion
    from packaging.version import Version
except ImportError:  # pragma: no cover - packaging ships with pip
    InvalidVersion = ValueError
    Version = None

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "requirements.txt"

PIN = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>\S+)")
GIT = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s+@\s+(?P<url>\S+)")
EDITABLE = re.compile(r"^-e\s+\S+#egg=(?P<name>[A-Za-z0-9._-]+)")


def canonical(name):
    """Return the normalized distribution name, as pip compares them."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse(text):
    """Split a freeze-like text into pinned versions and git entries."""
    pins = {}
    git = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if match := EDITABLE.match(line):
            git.setdefault(canonical(match["name"]), "")
        elif match := GIT.match(line):
            git.setdefault(canonical(match["name"]), match["url"])
        elif match := PIN.match(line):
            pins.setdefault(canonical(match["name"]), (match["name"], match["version"]))
    return pins, git


def compare(there, here):
    """Return -1, 0 or 1 comparing the target version with the reference one."""
    if Version is not None:
        try:
            left, right = Version(there), Version(here)
        except InvalidVersion:
            pass
        else:
            return (left > right) - (left < right)
    return (there > here) - (there < here)


def read(source):
    """Return the text of a freeze file, or of the standard input for ``-``."""
    if source == "-":
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        return sys.stdin.read()
    path = Path(source)
    # utf-8-sig: a freeze written by PowerShell may start with a BOM.
    return path.read_text(encoding="utf-8-sig")


def report(label, reference, target):
    """Print the differences between the reference and the target machine."""
    ref_pins, ref_git = reference
    new_pins, new_git = target

    older, newer, same = [], [], []
    for name, (shown, here) in ref_pins.items():
        if name not in new_pins:
            continue
        there = new_pins[name][1]
        verdict = compare(there, here)
        if verdict < 0:
            older.append((shown, there, here))
        elif verdict > 0:
            newer.append((shown, there, here))
        else:
            same.append(shown)
    older.sort(key=lambda row: row[0].lower())
    newer.sort(key=lambda row: row[0].lower())
    same.sort(key=str.lower)

    missing = sorted(
        shown for name, (shown, _) in ref_pins.items() if name not in new_pins
    )
    extra = sorted(
        shown for name, (shown, _) in new_pins.items() if name not in ref_pins
    )

    print(f"Reference: {REFERENCE}")
    print(f"Compared with: {label}")
    print(f"Older there ({len(older)}) - adapt the code to these:")
    for shown, there, here in older:
        print(f"  {shown:<28} {there:<14} < {here}")
    print(f"Newer there ({len(newer)}):")
    for shown, there, here in newer:
        print(f"  {shown:<28} {there:<14} > {here}")
    print(f"Identical ({len(same)}): {', '.join(same) if len(same) < 12 else '...'}")
    print(f"Missing there ({len(missing)}): {', '.join(missing) or 'none'}")
    print(f"Not pinned there ({len(extra)}): {', '.join(extra) or 'none'}")
    git_names = ", ".join(sorted(set(ref_git) | set(new_git)))
    print(f"Git checkouts, not compared: {git_names or 'none'}")
    print(f"Pinned entries compared: {len(ref_pins)}")
    print(
        f"  older: {len(older)}, newer: {len(newer)}, identical: {len(same)}, "
        f"missing: {len(missing)}, extra: {len(extra)}"
    )


def main():
    """Compare one freeze with requirements.txt and return an exit code."""
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if len(args) > 1:
        print(__doc__)
        return 2
    source = args[0] if args else "-"
    try:
        text = read(source)
        reference_text = REFERENCE.read_text(encoding="utf-8")
    except OSError as error:
        print(f"cannot read: {error}")
        return 2
    label = "standard input" if source == "-" else source
    report(label, parse(reference_text.lstrip("\ufeff")), parse(text.lstrip("\ufeff")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
