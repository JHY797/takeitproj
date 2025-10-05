#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, time, re, pandas as pd, requests
from dotenv import load_dotenv

# ───────────────────── Config ─────────────────────
load_dotenv()
API_KEY   = os.getenv("GOOGLE_API_KEY")
SEARCH_URL  = "https://maps.googleapis.com/maps/api/place/textsearch/json"
DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

LANG = "ro"
REGION = "md"
SLEEP = 1.0                 # crește la 1.2 dacă vezi OVER_QUERY_LIMIT
BATCH_SAVE_EVERY = 10       # salvează la fiecare N rânduri

CITY_CENTER = {
    "Chișinău": (47.0105, 28.8638),
    "Bălți": (47.753, 27.919), "Cahul": (45.904, 28.194),
    "Orhei": (47.384, 28.824), "Soroca": (48.155, 28.287),
    "Ungheni": (47.212, 27.811), "Ialoveni": (46.946, 28.782),
    "Hîncești": (46.829, 28.589), "Călărași": (47.258, 28.308),
    "Edineț": (48.168, 27.312), "Drochia": (48.034, 27.816),
    "Rezina": (47.748, 28.965), "Rîșcani": (47.955, 27.563),
    "Telenești": (47.506, 28.364), "Durlești": (47.026, 28.747),
    "Sîngera": (46.922, 28.963), "Anenii Noi": (46.879, 29.234),
    "Comrat": (46.296, 28.656), "Ceadîr-Lunga": (46.062, 28.830),
    "Nisporeni": (47.082, 28.176),
}

CITY_FIX = {
    "CHISINAU":"Chișinău","CHIȘINĂU":"Chișinău","BALTI":"Bălți","BĂLȚI":"Bălți",
    "HINCESTI":"Hîncești","HÎNCEȘTI":"Hîncești","CALARASI":"Călărași","CĂLĂRAȘI":"Călărași",
    "EDINET":"Edineț","EDINEȚ":"Edineț","FALESTI":"Fălești","FĂLEȘTI":"Fălești",
    "FLORESTI":"Florești","FLOREȘTI":"Florești","RISCANI":"Rîșcani","RÎȘCANI":"Rîșcani",
    "SINGEREI":"Sîngerei","SÎNGEREI":"Sîngerei","SINGERA":"Sîngera","SÎNGERA":"Sîngera",
    "TELENESTI":"Telenești","TELENEȘTI":"Telenești","VADUL LUI VODA":"Vadul lui Vodă",
    "VADUL LUI VODĂ":"Vadul lui Vodă","CAHUL":"Cahul","SOROCA":"Soroca","ORHEI":"Orhei",
    "REZINA":"Rezina","UNGHENI":"Ungheni","ANENII NOI":"Anenii Noi","COMRAT":"Comrat",
    "DURLESTI":"Durlești","DURLEȘTI":"Durlești","CUPCINI":"Cupcini","NISPORENI":"Nisporeni"
}

PREFIX_MAP = {
    "CREANGA ION":"Strada Ion Creangă","ALECSANDRI VASILE":"Strada Vasile Alecsandri",
    "MUNCESTI":"Bulevardul Muncesti","MIRCEA CEL BATRIN":"Bulevardul Mircea cel Bătrîn",
    "MIRCEA CEL BĂTRÎN":"Bulevardul Mircea cel Bătrîn","MOSCOVA":"Bulevardul Moscova",
    "DACIA":"Bulevardul Dacia","INDEPENDENTEI":"Strada Independenței","INDEPENDENȚEI":"Strada Independenței",
    "GRIGORE VIERU":"Bulevardul Grigore Vieru","TRAIAN":"Bulevardul Traian",
    "ALBA-IULIA":"Bulevardul Alba Iulia","ALBA IULIA":"Bulevardul Alba Iulia",
    "GHIBU ONISIFOR":"Strada Onisifor Ghibu","TITULESCU NICOLAE":"Strada Nicolae Titulescu",
    "CANTEMIR DIMITRIE":"Bulevardul Dimitrie Cantemir","CALEA IESILOR":"Calea Ieșilor",
    "SARMIZEGETUSA":"Strada Sarmizegetusa","ALBISOARA":"Strada Albișoara",
    "LUPU VASILE":"Strada Vasile Lupu","DECEBAL":"Bulevardul Decebal",
    "SCIUSEV ALEXEI":"Strada Alexei Sciusev","CUZA-VODA":"Strada Cuza Vodă","CUZA VODA":"Strada Cuza Vodă",
    "PARIS":"Strada Paris"
}

# ───────────────────── Utils ─────────────────────
def tnorm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip(" ,")

def filled(x) -> bool:
    if pd.isna(x): return False
    s = str(x).strip()
    return s != "" and s.lower() != "nan"

def fix_city(raw_city: str) -> str:
    key = tnorm(raw_city).upper()
    return CITY_FIX.get(key, raw_city.title())

def split_address(addr: str):
    parts = [p for p in [p.strip() for p in addr.split(",")] if p]
    if not parts: return "", []
    return parts[0], parts[1:]

def build_street(parts):
    rest = " ".join([tnorm(p) for p in parts if tnorm(p)]).replace("/", " / ")
    tokens = [t for t in re.split(r"[,\s]+", rest) if t]
    if not tokens: return "", ""
    house = ""
    if re.match(r"^\d+[A-Za-z]?(/?\d+[A-Za-z]?)?$", tokens[-1]):
        house = tokens[-1]; tokens = tokens[:-1]
    street_raw = " ".join(tokens).upper()
    street = PREFIX_MAP.get(street_raw, street_raw.title())
    return street, house

def normalize_address(address: str):
    city_raw, rest = split_address(address)
    if not city_raw and not rest: return "", ""
    city = fix_city(city_raw)
    street, nr = build_street(rest)
    base = f"{street} {nr}".strip()
    return city, base

# ───────────────── Google Places ────────────────
def textsearch(query: str, bias=None):
    params = {"query": query, "key": API_KEY, "language": LANG, "region": REGION}
    if bias:
        lat, lon = bias
        params.update({"location": f"{lat},{lon}", "radius": 20000})
    j = requests.get(SEARCH_URL, params=params, timeout=30).json()
    status = j.get("status")
    if status != "OK":
        print(f"   • Google status: {status} {j.get('error_message','')}")
    return j.get("results", [])

def details(place_id: str):
    params = {
        "place_id": place_id,
        "fields": "opening_hours,geometry,name,formatted_address",
        "key": API_KEY, "language": LANG, "region": REGION
    }
    return requests.get(DETAILS_URL, params=params, timeout=30).json().get("result", {})

def pick_best(results, want_city, want_street):
    want_city_l = (want_city or "").lower()
    want_street_l = (want_street or "").lower()
    scored = []
    for it in results:
        name = (it.get("name","") or "").lower()
        addr = (it.get("formatted_address","") or it.get("vicinity","") or "").lower()
        s = 0
        if "linella" in name: s += 3
        if want_city_l and want_city_l in addr: s += 2
        frag = want_street_l[:12].strip()
        if frag and frag in addr: s += 2
        if "chișinău" in addr or "chisinau" in addr: s += 1
        scored.append((s, it))
    if not scored: return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored[0][0] > 0 else None

def fetch_for_address(address: str):
    city, street = normalize_address(address)
    if not city and not street: return None
    bias = CITY_CENTER.get(city)
    queries = []
    if street:
        queries += [
            f"Linella {street}, {city}, Moldova",
            f"Linella {street} {city}",
            f"Linella {city} {street}",
        ]
    queries += [f"Linella {city}, Moldova", f"Linella {city}"]
    for q in queries:
        res = textsearch(q, bias=bias); time.sleep(SLEEP)
        if not res: continue
        cand = pick_best(res, city, street)
        if cand: return cand
    return None

def google_hours_to_dict(weekday_text):
    day_map = ["mon","tue","wed","thu","fri","sat","sun"]
    hours = {d:"" for d in day_map}
    for i, line in enumerate(weekday_text[:7]):
        parts = line.split(": ", 1)
        hours[day_map[i]] = parts[1] if len(parts)==2 else ""
    return hours

# ───────────────────── Main ─────────────────────
def main():
    if not API_KEY:
        raise SystemExit("Lipsește GOOGLE_API_KEY în .env")

    in_path  = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "linella_master.xlsx")
    out_path = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else "linella_google_full.xlsx")

    print(f"CWD:  {os.getcwd()}")
    print(f"IN :  {in_path}")
    print(f"OUT:  {out_path}")

    df = pd.read_excel(in_path)

    # asigură coloanele și normalizează NaN → ""
    days = ["mon","tue","wed","thu","fri","sat","sun"]
    for col in ["lat","lon","status", *days]:
        if col not in df.columns: df[col] = ""
    df[["lat","lon","status", *days]] = df[["lat","lon","status", *days]].applymap(
        lambda v: "" if (pd.isna(v) or str(v).strip().lower()=="nan") else v
    )

    total = len(df); ok = miss = 0

    for i, row in df.iterrows():
        nr   = row.get("number", i+1)
        addr = str(row.get("address", "")).strip()
        print(f"🔎 [{i+1}/{total}] Linella {nr} → {addr}")

        if not addr:
            df.at[i, "status"] = "MISS"; miss += 1
            print("   ⚠️  lipsă adresă → MISS")
            continue

        try:
            place = fetch_for_address(addr)
            if not place:
                df.at[i, "status"] = "MISS"; miss += 1
                print("   ❌ MISS (nu am găsit)")
                continue

            lat0 = place["geometry"]["location"]["lat"]
            lng0 = place["geometry"]["location"]["lng"]

            det = details(place["place_id"]); time.sleep(SLEEP)
            loc2 = (det.get("geometry") or {}).get("location") or {}

            lat_final = float(loc2.get("lat", lat0))
            lon_final = float(loc2.get("lng", lng0))

            df.at[i, "lat"] = lat_final
            df.at[i, "lon"] = lon_final

            weekday_text = (det.get("opening_hours") or {}).get("weekday_text", [])
            for d, v in google_hours_to_dict(weekday_text).items():
                df.at[i, d] = v

            df.at[i, "status"] = "OK"; ok += 1
            print(f"   ✅ OK → {lat_final}, {lon_final}")

            if (i+1) % BATCH_SAVE_EVERY == 0:
                df.to_excel(out_path, index=False)
                print("   💾 progres salvat…")

        except Exception as e:
            df.at[i, "status"] = "MISS"; miss += 1
            print(f"   ❗ Eroare: {e}")

    # conversie sigură în numerice
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")

    df.to_excel(out_path, index=False)
    print(f"✅ Gata. Scris în {out_path}")
    print(f"Rezumat: OK={ok}  MISS={miss}  TOTAL={total}")

if __name__ == "__main__":
    main()
