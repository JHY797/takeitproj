#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, json, pandas as pd

IN_XLSX = "linella_google_full.xlsx"
OUT_DIR  = "data"
CSV_OUT  = os.path.join(OUT_DIR, "linella_for_bot.csv")
JSON_OUT = os.path.join(OUT_DIR, "linella_for_bot.json")
GEOJSON_OUT = os.path.join(OUT_DIR, "linella_for_map.geojson")

NEEDED = ["number","address","lat","lon","mon","tue","wed","thu","fri","sat","sun","status"]

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    df = pd.read_excel(IN_XLSX)

    # asigură coloană lipsă
    for c in NEEDED:
        if c not in df.columns: df[c] = ""

    # păstrăm doar rândurile OK
    ok = df[df["status"].astype(str).str.upper().eq("OK")].copy()

    # formatare coordonate (max 6 zecimale)
    ok["lat"] = pd.to_numeric(ok["lat"], errors="coerce").round(6)
    ok["lon"] = pd.to_numeric(ok["lon"], errors="coerce").round(6)

    # CSV simplu pentru bot (în ordinea dorită)
    cols_csv = ["number","address","lat","lon","mon","tue","wed","thu","fri","sat","sun"]
    ok.to_csv(CSV_OUT, index=False, columns=cols_csv)
    print(f"✅ CSV scris: {CSV_OUT}  (rows={len(ok)})")

    # JSON pentru căutare rapidă după număr
    recs = []
    for _, r in ok.iterrows():
        recs.append({
            "number": int(r["number"]),
            "address": str(r["address"]),
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "hours": {
                "mon": str(r["mon"]), "tue": str(r["tue"]), "wed": str(r["wed"]),
                "thu": str(r["thu"]), "fri": str(r["fri"]), "sat": str(r["sat"]), "sun": str(r["sun"])
            }
        })

    # dict indexat după număr
    by_num = {str(x["number"]): x for x in recs}
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(by_num, f, ensure_ascii=False, indent=2)
    print(f"✅ JSON scris: {JSON_OUT}")

    # GeoJSON (opțional)
    features = []
    for x in recs:
        features.append({
            "type":"Feature",
            "geometry":{"type":"Point","coordinates":[x["lon"], x["lat"]]},
            "properties":{"number": x["number"], "address": x["address"]}
        })
    geojson = {"type":"FeatureCollection","features":features}
    with open(GEOJSON_OUT, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False)
    print(f"✅ GeoJSON scris: {GEOJSON_OUT}")

    # rezumat
    print(f"Done. Exportate {len(ok)} locații din {len(df)} total.")

if __name__ == "__main__":
    main()
