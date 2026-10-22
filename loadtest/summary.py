"""Print the results of loadtest/run.sh as a table: one row per level, then the slowest pages.

Usage: python loadtest/summary.py loadtest/results/<run>
"""

import csv
import re
import sys
from pathlib import Path


def read(path: Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def main(folder: Path) -> None:
    runs = sorted(folder.glob("u*_stats.csv"), key=lambda p: int(re.search(r"u(\d+)_", p.name).group(1)))
    print(f"{'Benutzer':>8} {'Req/s':>7} {'p50':>6} {'p95':>6} {'p99':>6} {'max':>6} {'Fehler':>7}")
    for path in runs:
        users = re.search(r"u(\d+)_", path.name).group(1)
        total = next(r for r in read(path) if r["Name"] == "Aggregated")
        print(
            f"{users:>8} {float(total['Requests/s']):>7.1f} {total['50%']:>6} {total['95%']:>6} {total['99%']:>6} "
            f"{float(total['Max Response Time']):>6.0f} {total['Failure Count']:>7}"
        )
    if not runs:
        return
    print(f"\nLangsamste Seiten bei {re.search(r'u(\d+)_', runs[-1].name).group(1)} Benutzern (p95 in ms):")
    rows = [r for r in read(runs[-1]) if r["Name"] != "Aggregated" and int(r["Request Count"])]
    for r in sorted(rows, key=lambda r: -float(r["95%"]))[:8]:
        print(f"  {r['95%']:>6}  p50 {r['50%']:>5}  {r['Type']:<4} {r['Name']}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
