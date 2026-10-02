"""Judge the live decisions of a piloted run after the fact (the rollback's verdict).

Run it with:
    python plugins/gemseo_lso/benchmarks/analyze_decisions.py <journal.jsonl> [...]

For each change of live settings in a journal of the Claude copilot, it compares
the outer iterations that follow the change with the ones before it, as the
pilot does while the run goes on (``gemseo_claude_pilot.progress.harm``), and
prints what the verdict would have been. It reads the journal only, so it can
calibrate the thresholds on runs already made.
"""

import json
import sys
from pathlib import Path

from gemseo_claude_pilot.progress import TrialSettings
from gemseo_claude_pilot.progress import harm
from gemseo_claude_pilot.progress import progress

LIVE_KINDS = ("change_settings", "switch_algorithm")


def verdicts(journal: Path, settings: TrialSettings) -> list[str]:
    """What the pilot would have said of each live change of a journal."""
    rows = [json.loads(line) for line in journal.read_text("utf-8").splitlines()]
    reports = [row for row in rows if row["kind"] == "algorithm"]
    lines = []
    seen = 0
    for row in rows:
        if row["kind"] == "algorithm":
            seen += 1
        elif row["kind"] == "decision" and row.get("live"):
            action = row["decision"]["action"]
            if action["kind"] not in LIVE_KINDS:
                continue
            window = settings.window
            before = progress(reports[max(seen - window, 0) : seen])
            after = progress(reports[seen : seen + window])
            what = json.dumps(action.get("settings") or action.get("algo_name"))
            if before is None or after is None or after.iterations < window:
                lines.append(f"after iteration {seen}: {what}: too few iterations")
                continue
            reason = harm(before, after, settings)
            verdict = f"WOULD BE UNDONE ({reason})" if reason else "kept"
            lines.append(
                f"after iteration {seen}: {what}: gain/iteration "
                f"{before.gain:.3%} -> {after.gain:.3%}, violation "
                f"{before.violation:.3g} -> {after.violation:.3g}, KKT "
                f"{before.kkt:.3g} -> {after.kkt:.3g}: {verdict}"
            )
    return lines


def main(paths: list[str]) -> None:
    """Print the verdicts of the journals."""
    for path in paths:
        print(path)
        for line in verdicts(Path(path), TrialSettings()):
            print("  " + line)


if __name__ == "__main__":
    main(sys.argv[1:])
