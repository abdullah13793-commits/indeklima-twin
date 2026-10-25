"""Ingest raw MQTT-style JSONL messages into a tidy 5-minute table (Parquet), queryable with DuckDB.

Topic schema: site/b308/<storey>/<room>/<env|vav|occ>  and  site/b308/roof/weather
"""
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "data" / "store"


def ingest(raw_dir=ROOT / "data" / "raw"):
    STORE.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    files = str(raw_dir / "*.jsonl").replace("\\", "/")
    con.execute(f"""
        CREATE OR REPLACE TABLE msg AS
        SELECT CAST(ts AS TIMESTAMP) AS ts, topic,
               split_part(topic, '/', 3) AS storey, split_part(topic, '/', 4) AS room,
               CASE WHEN topic LIKE '%/weather' THEN 'weather' ELSE split_part(topic, '/', 5) END AS kind,
               TRY_CAST(co2 AS DOUBLE) co2, TRY_CAST(t AS DOUBLE) t, TRY_CAST(rh AS DOUBLE) rh,
               TRY_CAST(q_ls AS DOUBLE) q_ls, TRY_CAST(count AS DOUBLE) occ,
               TRY_CAST(t_out AS DOUBLE) t_out, TRY_CAST(rh_out AS DOUBLE) rh_out, TRY_CAST(ghi AS DOUBLE) ghi
        FROM read_json_auto('{files}', format='newline_delimited', union_by_name=true)""")
    n_msg = con.execute("SELECT count(*) FROM msg").fetchone()[0]
    n_wx = con.execute("SELECT count(*) FROM msg WHERE kind = 'weather'").fetchone()[0]
    assert n_wx > 0, "no weather messages ingested"
    rooms = con.execute("""
        SELECT time_bucket(INTERVAL 5 MINUTE, ts) AS ts, storey, room,
               avg(co2) co2, avg(t) t, avg(rh) rh, avg(q_ls) q_ls, avg(occ) occ
        FROM msg WHERE kind IN ('env','vav','occ') GROUP BY ALL ORDER BY room, ts""").df()
    wx = con.execute("""
        SELECT time_bucket(INTERVAL 5 MINUTE, ts) AS ts, avg(t_out) t_out, avg(rh_out) rh_out, avg(ghi) ghi
        FROM msg WHERE kind = 'weather' GROUP BY ALL ORDER BY ts""").df()
    rooms.to_parquet(STORE / "rooms_5min.parquet", index=False)
    wx.to_parquet(STORE / "weather_5min.parquet", index=False)
    return dict(messages=int(n_msg), rows=len(rooms), rooms=int(rooms.room.nunique()))


def load():
    r = pd.read_parquet(STORE / "rooms_5min.parquet")
    w = pd.read_parquet(STORE / "weather_5min.parquet")
    return r, w


if __name__ == "__main__":
    print(ingest())
