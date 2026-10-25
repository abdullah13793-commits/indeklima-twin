"""Robustness study: the detector thresholds were set on seed 308. Re-run the whole chain on unseen seeds
(new occupancy, sensor noise, device offsets, message loss) and record recall / false alarms / ACH error.
Restores the canonical seed-308 data at the end."""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import simulate  # noqa: E402
import run_all  # noqa: E402
from validate_ach import ach_error  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
rows = []
HELD_OUT = {11, 12, 13, 14, 15}   # never seen while the detector was designed (seeds 1-10 + 308 were used for development)
for seed in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 308]:
    with contextlib.redirect_stdout(io.StringIO()):
        simulate.simulate(seed=seed)
        ev = run_all.main()
    err = ach_error()
    rows.append(dict(seed=seed, held_out=seed in HELD_OUT, recall_building=ev["recall_building"], recall_data=ev["recall_data"],
                     false_alarms=ev["n_false_alarms"], ach_median_abs_err=err["median_abs_err"],
                     missed=[f["fault"] for f in ev["faults"] if not f["detected"]],
                     false=[(f.get("rule") or f["type"], f["room"]) for f in ev["false_alarms"]]))
    print(rows[-1], flush=True)
json.dump(rows, open(ROOT / "results" / "robustness.json", "w"), indent=1)
