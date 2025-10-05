#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, re, json, math, argparse, datetime as dt
from typing import List, Tuple, Dict, Any
from urllib.parse import urlencode
import requests
from dotenv import load_dotenv

# ───────── Config ─────────
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")  # ai zis că așa se numește la tine
if not GOOGLE_API_KEY:
    raise SystemExit("❌ Lipsă GOOGLE_API_KEY în .env")

DATA_DIR = "data"
BRANDS = {
    "l":  ("Linella",     "linella_for_bot.json"),
    "f":  ("Fidesco",     "fidesco_for_bot.json"),
    "c":  ("Cip",         "cip_for_bot.json"),
    "m":  ("Merci",       "merci_for_bot.json"),
    "fo": ("Fourchette",  "fourchette_for_bot.json"),
    "t":  ("TOT",         "tot_for_bot.json"),
}

# ───────── Helpers ─────────
def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl   = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))

def fmt_dur(seconds: int) -> str:
    m = max(0, int(round(seconds/60)))
    h, m = divmod(m, 60)
    return f"{h}h {m}m" if h else f"{m}m"

def build_gmaps_directions_url(points: List[Tuple[float,float]]) -> str:
    if not points or len(points) < 2:
        return ""
    origin = "{:.6f},{:.6f}".format(points[0][0], points[0][1])
    destination = "{:.6f},{:.6f}".format(points[-1][0], points[-1][1])
    waypoints = "|".join("{:.6f},{:.6f}".format(lat,lon) for lat,lon in points[1:-1]) if len(points) > 2 else ""
    url = "https://www.google.com/maps/dir/?api=1"
    q = {"origin": origin, "destination": destination}
    if waypoints:
        q["waypoints"] = waypoints
    return url + "&" + urlencode(q)

# ───────── Date ─────────
def load_json_dict(file_name: str) -> Dict[str, Any]:
    path = os.path.join(DATA_DIR, file_name)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    return {str(k): v for k, v in d.items()}

DATA_BY_BRAND: Dict[str, Dict[str, Any]] = {}
for code, (_, fname) in BRANDS.items():
    DATA_BY_BRAND[code] = load_json_dict(fname)

# ───────── Parsare input ─────────
def parse_multi_codes(text: str) -> List[Tuple[str,int]]:
    picks = re.findall(r"(?i)(lin|fid|cip|mer|fo|fourchette|t|tot|l|f|c|m)\s*(\d{1,3})", text)
    out = []
    for pref, num in picks:
        pref = pref.lower()
        if pref in ("fo","fourchette"): code = "fo"
        elif pref in ("lin","l"):       code = "l"
        elif pref in ("fid","f"):       code = "f"
        elif pref in ("cip","c"):       code = "c"
        elif pref in ("mer","m"):       code = "m"
        elif pref in ("t","tot"):       code = "t"
        else: continue
        out.append((code, int(num)))
    return out

def get_points_and_labels(pairs: List[Tuple[str,int]]) -> Tuple[List[Tuple[float,float]], List[str]]:
    coords, labels = [], []
    for code, num in pairs:
        d = DATA_BY_BRAND.get(code, {})
        item = d.get(str(num))
        if not item:
            raise SystemExit(f"❌ Nu găsesc {BRANDS[code][0]} {num} în {BRANDS[code][1]}")
        lat = float(item.get("lat") or 0.0)
        lon = float(item.get("lon") or 0.0)
        if not lat or not lon:
            raise SystemExit(f"❌ {BRANDS[code][0]} {num} nu are coordonate valide")
        coords.append((lat, lon))
        labels.append(f"{BRANDS[code][0]} {num} — {item.get('address','—')}")
    return coords, labels

# ───────── Distance Matrix (cu trafic) ─────────
def distance_matrix_seconds(origins: List[Tuple[float,float]], destinations: List[Tuple[float,float]]) -> List[List[int]]:
    base = "https://maps.googleapis.com/maps/api/distancematrix/json"
    o_param = "|".join("{:.6f},{:.6f}".format(lat, lon) for lat,lon in origins)
    d_param = "|".join("{:.6f},{:.6f}".format(lat, lon) for lat,lon in destinations)
    params = {
        "origins": o_param,
        "destinations": d_param,
        "mode": "driving",
        "departure_time": "now",
        "traffic_model": "best_guess",
        "key": GOOGLE_API_KEY
    }
    r = requests.get(base, params=params, timeout=20)
    r.raise_for_status()
    js = r.json()
    if js.get("status") != "OK":
        raise RuntimeError(f"DistanceMatrix status: {js.get('status')}")
    rows = js.get("rows", [])
    mat = []
    for row in rows:
        arr = []
        for el in row.get("elements", []):
            if el.get("status") != "OK":
                arr.append(10**9)
            else:
                sec = el.get("duration_in_traffic", el.get("duration", {})).get("value", 10**9)
                arr.append(int(sec))
        mat.append(arr)
    return mat

# ───────── TSP: nearest neighbor + 2-opt ─────────
def tsp_nearest_then_two_opt(dmat: List[List[int]], start_idx: int = 0) -> List[int]:
    n = len(dmat)
    unvisited = set(range(n))
    path = [start_idx]
    unvisited.remove(start_idx)
    cur = start_idx
    while unvisited:
        nxt = min(unvisited, key=lambda j: dmat[cur][j])
        path.append(nxt)
        unvisited.remove(nxt)
        cur = nxt

    def path_cost(p):
        return sum(dmat[p[i]][p[i+1]] for i in range(len(p)-1))

    improved = True
    best = path[:]
    best_cost = path_cost(best)
    while improved:
        improved = False
        for i in range(1, len(best)-2):
            for k in range(i+1, len(best)-1):
                newp = best[:i] + best[i:k+1][::-1] + best[k+1:]
                c = path_cost(newp)
                if c < best_cost:
                    best, best_cost = newp, c
                    improved = True
    return best

# ───────── Main CLI ─────────
def main():
    ap = argparse.ArgumentParser(description="Optimizează ruta între magazine (trafic live, Distance Matrix).")
    ap.add_argument("query", help='Ex: "l5 c30 fo70" sau "l5, c30, fo70"')
    ap.add_argument("--origin", help="Lat,Lon pentru punctul de start (ex: 47.010,28.863). Dacă lipsește, start = primul punct.")
    args = ap.parse_args()

    pairs = parse_multi_codes(args.query)
    if len(pairs) < 2:
        # încearcă o separare prin spații/virgule
        tokens = [t for t in re.split(r"[,\s]+", args.query.strip()) if t]
        pairs = []
        for t in tokens:
            m = re.match(r"(?i)^(lin|fid|cip|mer|fo|fourchette|t|tot|l|f|c|m)\s*(\d{1,3})$", t)
            if m:
                pairs.append((m.group(1).lower(), int(m.group(2))))
        if len(pairs) < 2:
            raise SystemExit("❌ Dă-mi cel puțin două locații. Exemplu: l5 c30 fo70")

    # normalizează prefixele în codurile noastre
    norm = []
    for pref, num in pairs:
        pref = pref.lower()
        if pref in ("fo","fourchette"): code = "fo"
        elif pref in ("lin","l"):       code = "l"
        elif pref in ("fid","f"):       code = "f"
        elif pref in ("cip","c"):       code = "c"
        elif pref in ("mer","m"):       code = "m"
        elif pref in ("t","tot"):       code = "t"
        else: continue
        norm.append((code, int(num)))
    if len(norm) < 2:
        raise SystemExit("❌ Nu am putut interpreta locațiile.")

    coords, labels = get_points_and_labels(norm)

    # ORIGIN
    if args.origin:
        try:
            lat_s, lon_s = args.origin.split(",")
            origin = (float(lat_s.strip()), float(lon_s.strip()))
            # set-up TSP pe puncte: origin + destinațiile
            pts = [origin] + coords
            mat = distance_matrix_seconds(pts, pts)
            order = tsp_nearest_then_two_opt(mat, start_idx=0)
            ordered_idx = [i for i in order if i != 0]
            ordered_points = [pts[i] for i in ordered_idx]
            ordered_labels = [labels[i-1] for i in ordered_idx]
            total_s = 0
            for a, b in zip([0] + ordered_idx[:-1], ordered_idx):
                total_s += mat[a][b]
            url = build_gmaps_directions_url([origin] + ordered_points)
            print("🚗 Rută optimizată (trafic actual, start = origin dat):")
            print(f"Durată estimată: ~{fmt_dur(total_s)}\n")
            for i, name in enumerate(ordered_labels, 1):
                print(f"{i}. {name}")
            print("\n🗺️", url)
            return
        except Exception as e:
            raise SystemExit(f"❌ Eroare origin: {e}")

    # fără origin -> start din primul punct
    mat = distance_matrix_seconds(coords, coords)
    order = tsp_nearest_then_two_opt(mat, start_idx=0)
    ordered_points = [coords[i] for i in order]
    ordered_labels = [labels[i] for i in order]
    total_s = sum(mat[a][b] for a, b in zip(order[:-1], order[1:]))
    url = build_gmaps_directions_url(ordered_points)
    print("🚗 Rută optimizată (trafic actual, start = primul punct):")
    print(f"Durată estimată: ~{fmt_dur(total_s)}\n")
    for i, name in enumerate(ordered_labels, 1):
        print(f"{i}. {name}")
    print("\n🗺️", url)

if __name__ == "__main__":
    main()
