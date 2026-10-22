#!/bin/sh
# Run the load test at several concurrency levels and keep one CSV summary per level.
# Usage: loadtest/run.sh [host] [seconds per level]
#   LEVELS="5 10 20"    simulated users per level
#   RATE=2              users that start per second
#   LOADTEST_WAIT=0     no pause between clicks (maximum throughput)
set -eu

HOST=${1:-http://localhost:8000}
DURATION=${2:-60}
LEVELS=${LEVELS:-"5 10 20 40"}
RATE=${RATE:-2}
OUT=${OUT:-loadtest/results/$(date +%Y%m%d-%H%M%S)}
mkdir -p "$OUT"

for users in $LEVELS; do
    echo "== $users Benutzer, ${DURATION}s"
    # The numbers start once all users have logged in (see locustfile.py), so add the time it takes to start them.
    uv run --with locust locust -f loadtest/locustfile.py --headless --only-summary \
        -u "$users" -r "$RATE" -t "$((DURATION + users / RATE + 5))s" -H "$HOST" --csv "$OUT/u$users" \
        >"$OUT/u$users.log" 2>&1 || true
done
echo
python3 loadtest/summary.py "$OUT"
echo "Ergebnisse: $OUT"
