"""End-to-end: raw JSONL -> store -> QC -> IEQ categories -> CO2-decay ventilation -> FDD -> results + web data."""
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from twin import ingest, qc, ieq, ventilation, fdd, evaluate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"


def main():
    t0 = time.time()
    RES.mkdir(exist_ok=True)
    design = json.load(open(ROOT / "data" / "room_design.json"))
    info = ingest.ingest()
    r, wx = ingest.load()
    r, qc_findings, qc_summary = qc.run(r)
    ieq_df = ieq.run(r)
    dec = ventilation.run(r, design)
    vent = ventilation.summarise(dec, design)
    findings = fdd.run(r, design, wx)
    ev = evaluate.evaluate(findings, qc_findings)
    ieq_df.to_json(RES / "ieq_by_room.json", orient="records", indent=1)
    dec.to_csv(RES / "co2_decay_windows.csv", index=False)
    vent.to_csv(RES / "ventilation_by_room.csv", index=False)
    json.dump(dict(ingest=info, qc=qc_summary, qc_findings=qc_findings), open(RES / "qc.json", "w"), indent=1, default=str)
    json.dump(findings, open(RES / "fdd_findings.json", "w"), indent=1, default=str)
    json.dump(ev, open(RES / "fdd_evaluation.json", "w"), indent=1, default=str)
    r.to_parquet(ROOT / "data" / "store" / "rooms_5min_clean.parquet", index=False)
    print(json.dumps(dict(ingest=info, qc=qc_summary, windows=len(dec), findings=len(findings),
                          recall_building=ev["recall_building"], recall_data=ev["recall_data"],
                          false_alarms=ev["n_false_alarms"], seconds=round(time.time() - t0, 1)), indent=1))
    for row in ev["faults"]:
        print(row)
    for fa in ev["false_alarms"]:
        print("FALSE ALARM:", {k: fa.get(k) for k in ("src", "rule", "type", "room", "period", "start", "evidence")})
    return ev


if __name__ == "__main__":
    main()
