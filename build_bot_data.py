#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_bot_data.py IN_XLSX OUT_CSV OUT_JSON

Citește un Excel „*_full.xlsx” (cu lat/lon + ore) și scrie:
- OUT_CSV (pentru inspecție/manual)
- OUT_JSON (dict pentru bot: { "10": {number, address, lat, lon, hours{mon..sun}} })
"""
import sys, os, json
import pandas as pd

def normalize_hours_cols(df):
    cols = [c.lower() for c in df.columns]
    map_cols = {c.lower(): c for c in df.columns}
    days = ["mon","tue","wed","thu","fri","sat","sun"]
    have_days = all(d in cols for d in days)

    if have_days:
        def get_hours_row(row):
            return {
                "mon": str(row[map_cols["mon"]]) if not pd.isna(row.get(map_cols["mon"])) else "",
                "tue": str(row[map_cols["tue"]]) if not pd.isna(row.get(map_cols["tue"])) else "",
                "wed": str(row[map_cols["wed"]]) if not pd.isna(row.get(map_cols["wed"])) else "",
                "thu": str(row[map_cols["thu"]]) if not pd.isna(row.get(map_cols["thu"])) else "",
                "fri": str(row[map_cols["fri"]]) if not pd.isna(row.get(map_cols["fri"])) else "",
                "sat": str(row[map_cols["sat"]]) if not pd.isna(row.get(map_cols["sat"])) else "",
                "sun": str(row[map_cols["sun"]]) if not pd.isna(row.get(map_cols["sun"])) else "",
            }
        return get_hours_row
    else:
        col = None
        for cand in ["opening_hours","hours","orar","program"]:
            if cand in cols:
                col = map_cols[cand]; break
        def get_hours_row(row):
            v = "" if (col is None or pd.isna(row.get(col))) else str(row[col])
            return {d: v for d in ["mon","tue","wed","thu","fri","sat","sun"]}
        return get_hours_row

def main():
    if len(sys.argv) < 4:
        print("Usage: build_bot_data.py IN_XLSX OUT_CSV OUT_JSON")
        sys.exit(1)
    in_xlsx, out_csv, out_json = sys.argv[1], sys.argv[2], sys.argv[3]
    if not os.path.exists(in_xlsx):
        raise SystemExit(f"❌ Missing input file: {in_xlsx}")

    df = pd.read_excel(in_xlsx)

    cols = {c.lower(): c for c in df.columns}
    def pick(*names):
        for n in names:
            if n in cols: return cols[n]
        return None

    c_number = pick("number","nr","id")
    c_address = pick("address","adresa","addr")
    c_lat = pick("lat","latitude","y")
    c_lon = pick("lon","longitude","x")

    if not c_number or not c_address:
        raise SystemExit("❌ Missing required columns: number/address")

    get_hours_row = normalize_hours_cols(df)

    out_rows = []
    data = {}
    for _, row in df.iterrows():
        try:
            n = int(row[c_number])
        except Exception:
            continue
        addr = "" if pd.isna(row.get(c_address)) else str(row[c_address]).strip()
        lat = row.get(c_lat); lon = row.get(c_lon)
        lat = float(lat) if pd.notna(lat) else 0.0
        lon = float(lon) if pd.notna(lon) else 0.0
        hours = get_hours_row(row)
        out_rows.append({"number": n, "address": addr, "lat": lat, "lon": lon, **hours})
        data[str(n)] = {"number": n, "address": addr, "lat": lat, "lon": lon, "hours": hours}

    os.makedirs(os.path.dirname(out_csv) or ".", exist_ok=True)
    pd.DataFrame(out_rows).sort_values("number").to_csv(out_csv, index=False, encoding="utf-8")

    os.makedirs(os.path.dirname(out_json) or ".", exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ CSV:  {os.path.abspath(out_csv)}")
    print(f"✅ JSON: {os.path.abspath(out_json)}")
    print(f"Rows: {len(out_rows)}")

if __name__ == "__main__":
    main()
