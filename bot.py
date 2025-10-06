#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
bot.py — handlers Aiogram 3.22 pentru proiectul tău (fără polling la import)
- expune: router
- nu instanțiază Bot/Dispatcher (le face server.py)
- folosește GOOGLE_API_KEY dacă există, altfel are fallback local
"""

import os
import re
import ssl
import json
import math
import asyncio
import datetime as dt
from typing import Dict, Any, Tuple, List, Optional
from zoneinfo import ZoneInfo

import aiohttp
import certifi
from dotenv import load_dotenv

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ─────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────
load_dotenv()  # permite .env local; pe Render folosești Environment tab

TZ = ZoneInfo("Europe/Chisinau")
DATA_DIR = "data"
GOOGLE_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_KEY")  # opțional

# Paginare listă
PER_PAGE = 20
BUTTONS_PER_ROW = 5

# brand code -> (nume public, json, start, end)
BRANDS: Dict[str, Tuple[str, str, int, int]] = {
    "l":  ("Linella",     "linella_for_bot.json",     1,   199),
    "f":  ("Fidesco",     "fidesco_for_bot.json",     101, 155),
    "c":  ("Cip",         "cip_for_bot.json",         1,   61),
    "m":  ("Merci",       "merci_for_bot.json",       1,   33),
    "fo": ("Fourchette",  "fourchette_for_bot.json",  60,  76),
    "t":  ("TOT",         "tot_for_bot.json",         71,  80),
}

# State per user (memorie în RAM; pentru Render e ok)
user_location: Dict[int, Tuple[float, float]] = {}
user_brand: Dict[int, str] = {}       # ultimul brand ales (pt numere simple)
user_route_mode: Dict[int, str] = {}  # "loc" | "first"

router = Router()  # <- Exportăm asta pentru server.py

# ─────────────────────────────────────────────────────────
# Utilitare
# ─────────────────────────────────────────────────────────
def user_tag(u) -> str:
    uname = f"@{getattr(u, 'username', '')}" if getattr(u, "username", None) else \
            f"{getattr(u, 'first_name', '')} {getattr(u, 'last_name', '')}".strip() or "<no-username>"
    return f"{uname} (#{u.id})"

def now_hms() -> str:
    return dt.datetime.now().strftime("%H:%M:%S")

def load_dict(fname: str) -> Dict[str, Any]:
    path = os.path.join(DATA_DIR, fname)
    if not os.path.exists(path):
        print(f"[WARN] Lipsește fișierul de date: {path}")
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        # cheia trebuie să fie string
        return {str(k): v for k, v in d.items()}
    except Exception as e:
        print(f"[ERR] {path}: {e}")
        return {}

DATA_BY_BRAND: Dict[str, Dict[str, Any]] = {}
MAX_BY_BRAND: Dict[str, int] = {}
for code, (_, fname, lo, hi) in BRANDS.items():
    d = load_dict(fname)
    DATA_BY_BRAND[code] = d
    nums = [int(k) for k in d.keys() if str(k).isdigit()]
    MAX_BY_BRAND[code] = min(max(nums) if nums else hi, hi)

print("[READY] brands:", {k: len(v) for k, v in DATA_BY_BRAND.items()})

def haversine_km(a1: float, b1: float, a2: float, b2: float) -> float:
    R = 6371.0088
    p1, p2 = math.radians(a1), math.radians(a2)
    dphi   = math.radians(a2 - a1)
    dl     = math.radians(b2 - b1)
    x = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * (2 * math.atan2(math.sqrt(x), math.sqrt(1-x)))

def today_key(now: Optional[dt.datetime] = None) -> str:
    now = now or dt.datetime.now(TZ)
    return ["mon","tue","wed","thu","fri","sat","sun"][now.weekday()]

_TIME_RGX = re.compile(r"(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})")

def parse_ranges(text: str) -> List[Tuple[dt.time, dt.time]]:
    out: List[Tuple[dt.time, dt.time]] = []
    for m in _TIME_RGX.finditer(text or ""):
        h1, m1, h2, m2 = map(int, m.groups())
        out.append((dt.time(h1, m1, tzinfo=TZ), dt.time(h2, m2, tzinfo=TZ)))
    return out

def is_open_now(day_text: str, now: Optional[dt.datetime] = None) -> bool:
    now = now or dt.datetime.now(TZ)
    tnow = now.timetz()
    for t1, t2 in parse_ranges(day_text):
        if t1 <= t2:
            if t1 <= tnow <= t2:
                return True
        else:  # peste miezul nopții
            if tnow >= t1 or tnow <= t2:
                return True
    return False

def format_hours(hours: Dict[str, str]) -> str:
    order = ["mon","tue","wed","thu","fri","sat","sun"]
    names = ["Luni","Marți","Miercuri","Joi","Vineri","Sâmbătă","Duminică"]
    return "\n".join(f"{n}: {hours.get(k,'') or '—'}" for k,n in zip(order, names))

def normalize_brand(s: str) -> Optional[str]:
    s = s.strip().lower()
    if s in BRANDS:
        return s
    if s.startswith("lin"): return "l"
    if s.startswith("fid"): return "f"
    if s.startswith("cip"): return "c"
    if s.startswith("mer"): return "m"
    if s in ("t", "tot") or s.startswith("tot"): return "t"
    if s.startswith("fo") or s.startswith("four"): return "fo"
    return None

def parse_code_token(tok: str) -> Optional[Tuple[str, int]]:
    t = tok.strip().lower()
    m = re.fullmatch(r"([a-z]{1,10})\s*(\d{1,3})", t, flags=re.IGNORECASE)
    if not m:
        return None
    code = normalize_brand(m.group(1))
    if not code:
        return None
    return code, int(m.group(2))

def parse_codes_line(text: str) -> List[Tuple[str, int]]:
    out: List[Tuple[str, int]] = []
    for tok in re.split(r"[,\s;|]+", (text or "").strip()):
        if not tok:
            continue
        p = parse_code_token(tok)
        if p:
            out.append(p)
    return out

# ─────────────────────────────────────────────────────────
# Keyboards
# ─────────────────────────────────────────────────────────
def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Linella"),    KeyboardButton(text="Fidesco")],
            [KeyboardButton(text="Cip"),        KeyboardButton(text="Merci")],
            [KeyboardButton(text="Fourchette"), KeyboardButton(text="TOT")],
            [KeyboardButton(text="📍 Trimite locația mea", request_location=True)],
            [KeyboardButton(text="🧭 Cale optimă"), KeyboardButton(text="🏠 Meniu")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )

def route_mode_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📍 De la locația mea", callback_data="route:loc"),
    ],[
        InlineKeyboardButton(text="🚩 De la primul magazin", callback_data="route:first"),
    ],[
        InlineKeyboardButton(text="🏠 Meniu", callback_data="home"),
    ]])

def page_kb(brand_code: str, page: int) -> InlineKeyboardMarkup:
    _, _, lo, hi = BRANDS[brand_code]
    max_num = MAX_BY_BRAND.get(brand_code, hi)
    start = lo + (page - 1) * PER_PAGE
    end   = min(max_num, hi, start + PER_PAGE - 1)
    if start > end:  # corecție de pagină
        start = max(lo, hi - PER_PAGE + 1)
        end   = min(max_num, hi)

    kb = InlineKeyboardBuilder()
    row: List[InlineKeyboardButton] = []
    for n in range(start, end + 1):
        row.append(InlineKeyboardButton(text=str(n), callback_data=f"i:{brand_code}:{n}"))
        if len(row) == BUTTONS_PER_ROW:
            kb.row(*row); row = []
    if row:
        kb.row(*row)

    nav = []
    if start > lo:
        nav.append(InlineKeyboardButton(text="◀️ Înapoi",  callback_data=f"p:{brand_code}:{page-1}"))
    if end < min(max_num, hi):
        nav.append(InlineKeyboardButton(text="▶️ Înainte", callback_data=f"p:{brand_code}:{page+1}"))
    if nav:
        kb.row(*nav)

    kb.row(InlineKeyboardButton(text="🏠 Revino la meniu", callback_data="home"))
    return kb.as_markup()

# ─────────────────────────────────────────────────────────
# Directions helpers
# ─────────────────────────────────────────────────────────
async def directions_optimize(origin: Tuple[float, float],
                              points: List[Tuple[float, float]]) -> Tuple[List[int], int]:
    """
    Întoarce (ordine_index, total_sec). Fallback local dacă nu avem Google Key sau request-ul eșuează.
    """
    if not points:
        return [], 0

    if not GOOGLE_KEY:
        # fallback simplu: ordonăm după distanța geodezică
        order = sorted(range(len(points)),
                       key=lambda i: haversine_km(origin[0], origin[1], points[i][0], points[i][1]))
        km = 0.0; cur = origin
        for i in order:
            km += haversine_km(cur[0], cur[1], points[i][0], points[i][1])
            cur = points[i]
        return order, int(km / 35 * 3600)  # ~35km/h

    # avem cheie → încercăm Directions API
    dest = points[-1]
    ways = points[:-1]
    params = {
        "origin": f"{origin[0]},{origin[1]}",
        "destination": f"{dest[0]},{dest[1]}",
        "mode": "driving",
        "departure_time": "now",
        "key": GOOGLE_KEY,
    }
    if ways:
        params["waypoints"] = "optimize:true|" + "|".join(f"{a},{b}" for a, b in ways)

    url = "https://maps.googleapis.com/maps/api/directions/json"
    ssl_ctx   = ssl.create_default_context(cafile=certifi.where())
    timeout   = aiohttp.ClientTimeout(total=18)
    connector = aiohttp.TCPConnector(ssl=ssl_ctx, limit=16)

    for _ in range(3):
        try:
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as s:
                async with s.get(url, params=params) as r:
                    data = await r.json()
            if data.get("status") == "OK":
                route = data["routes"][0]
                order = route.get("waypoint_order", list(range(len(ways))))
                total = 0
                for leg in route.get("legs", []):
                    d = leg.get("duration_in_traffic") or leg.get("duration") or {}
                    total += int(d.get("value", 0))
                return (order + [len(points) - 1], total)
        except Exception:
            await asyncio.sleep(0.8)

    # fallback local dacă Google eșuează
    order = sorted(range(len(points)),
                   key=lambda i: haversine_km(origin[0], origin[1], points[i][0], points[i][1]))
    km = 0.0; cur = origin
    for i in order:
        km += haversine_km(cur[0], cur[1], points[i][0], points[i][1])
        cur = points[i]
    return order, int(km / 35 * 3600)

def google_maps_url(origin: Optional[Tuple[float, float]],
                    ordered: List[Tuple[float, float]]) -> str:
    params = []
    if origin:
        params.append(("origin", f"{origin[0]},{origin[1]}"))
    if ordered:
        params.append(("destination", f"{ordered[-1][0]},{ordered[-1][1]}"))
        if len(ordered) > 1:
            w = "|".join(f"{a},{b}" for a, b in ordered[:-1])
            params.append(("waypoints", w))
    q = "&".join(f"{k}={v}" for k, v in params)
    return f"https://www.google.com/maps/dir/?api=1&{q}"

def waze_url(lat: float, lon: float) -> str:
    return f"https://waze.com/ul?ll={lat:.6f}%2C{lon:.6f}&navigate=yes"

def yandex_url(lat: float, lon: float) -> str:
    return f"https://yandex.com/maps/?rtext=~{lat:.6f}%2C{lon:.6f}&rtt=auto"

def links_kb_single(lat: float, lon: float) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗺️ Google Maps", url=f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}")
    ],[
        InlineKeyboardButton(text="🚗 Waze",        url=waze_url(lat, lon)),
        InlineKeyboardButton(text="🧭 Yandex Maps", url=yandex_url(lat, lon)),
    ],[
        InlineKeyboardButton(text="🏠 Revino la meniu", callback_data="home"),
    ]])

def links_kb_route(origin: Optional[Tuple[float, float]],
                   ordered: List[Tuple[float, float]]) -> InlineKeyboardMarkup:
    g = google_maps_url(origin, ordered)
    lat, lon = ordered[-1]
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗺️ Google Maps", url=g)
    ],[
        InlineKeyboardButton(text="🚗 Waze (destinație)",        url=waze_url(lat, lon)),
        InlineKeyboardButton(text="🧭 Yandex Maps (destinație)", url=yandex_url(lat, lon)),
    ],[
        InlineKeyboardButton(text="🏠 Revino la meniu", callback_data="home"),
    ]])

# ─────────────────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────────────────
async def show_item(message: Message, brand_code: str, n: int):
    if brand_code not in BRANDS:
        await message.answer("Lanț necunoscut. Folosește l/f/c/m/fo/t (ex: l10, fo70).", reply_markup=main_kb())
        return

    name, _, lo, hi = BRANDS[brand_code]
    if not (lo <= n <= hi):
        await message.answer(f"{name} are intervalul {lo}..{hi}. Ai cerut {n}.", reply_markup=main_kb())
        return

    data = DATA_BY_BRAND.get(brand_code, {})
    item = data.get(str(n))
    if not item:
        await message.answer(f"Nu am găsit {name} {n} în baza de date.", reply_markup=main_kb())
        return

    address = item.get("address", "—")
    lat = float(item.get("lat") or 0)
    lon = float(item.get("lon") or 0)
    hours = item.get("hours", {}) or {}
    today = today_key()
    today_txt = hours.get(today, "")
    opened = "🟢 Deschis acum" if (today_txt and is_open_now(today_txt)) else "🔴 Închis acum"

    dist_line = "📏 Distanță: — (apasă „📍 Trimite locația mea”)"
    if message.from_user and message.from_user.id in user_location and lat and lon:
        u_lat, u_lon = user_location[message.from_user.id]
        km = haversine_km(u_lat, u_lon, lat, lon)
        dist_line = f"📏 Distanță: ~{km:.2f} km"

    text = (
        f"🏪 {name} {n}\n"
        f"📍 {address}\n"
        f"📌 Coordonate: {lat:.6f}, {lon:.6f}\n"
        f"{dist_line}\n\n"
        f"{opened}\n"
        f"🕒 Program (azi: {today_txt or '—'})\n\n"
        f"{format_hours(hours)}"
    )
    await message.answer(text, reply_markup=links_kb_single(lat, lon))
    if lat and lon:
        await message.answer_location(latitude=lat, longitude=lon, reply_markup=main_kb())

@router.message(CommandStart())
async def start(message: Message):
    print(f"[{now_hms()}] MSG {user_tag(message.from_user)} -> /start")
    await message.answer(
        "ℹ️ Cum folosești botul\n\n"
        "1️⃣ Caută magazine\n"
        "• Scrie direct: l5, c30, fo70 etc.\n"
        "• Sau apasă lanțul și alege numărul.\n\n"
        "2️⃣ Detalii magazin\n"
        "• Adresă, program, deschis/închis, distanță, pin pe hartă.\n\n"
        "3️⃣ 📍 Trimite locația mea — ca să vezi distanțele.\n\n"
        "4️⃣ 🧭 Cale optimă — trimite o listă: l5 c30 fo70.\n",
        reply_markup=main_kb()
    )

@router.message(F.text == "🏠 Meniu")
async def back_to_menu(message: Message):
    user_brand.pop(message.from_user.id, None)
    await message.answer("Alege un lanț:", reply_markup=main_kb())

@router.callback_query(F.data == "home")
async def cb_home(cb: CallbackQuery):
    user_brand.pop(cb.from_user.id, None)
    await cb.answer()
    await cb.message.answer("🏠 Meniu", reply_markup=main_kb())

@router.message(F.location)
async def set_location(message: Message):
    user_location[message.from_user.id] = (message.location.latitude, message.location.longitude)
    await message.answer("✅ Locație salvată!", reply_markup=main_kb())

@router.message(F.text.in_(["Linella", "Fidesco", "Cip", "Merci", "Fourchette", "TOT"]))
async def pick_brand(message: Message):
    code = {"linella": "l", "fidesco": "f", "cip": "c", "merci": "m", "fourchette": "fo", "tot": "t"}[message.text.lower()]
    user_brand[message.from_user.id] = code
    name, _, lo, _ = BRANDS[code]
    await message.answer(f"Lista {name} – pagina 1:", reply_markup=ReplyKeyboardRemove())
    await message.answer("Alege un număr:", reply_markup=page_kb(code, 1))

@router.callback_query(F.data.startswith("p:"))
async def cb_page(cb: CallbackQuery):
    _, code, p = cb.data.split(":")
    await cb.answer()
    name = BRANDS[code][0]
    await cb.message.edit_text(f"Lista {name} – pagina {p}:")
    await cb.message.edit_reply_markup(reply_markup=page_kb(code, int(p)))

@router.callback_query(F.data.startswith("i:"))
async def cb_item(cb: CallbackQuery):
    _, code, n = cb.data.split(":")
    await cb.answer()
    await show_item(cb.message, code, int(n))

# „l5 / f105 / fo70 …”, tolerant la spații/case
@router.message(F.text.regexp(re.compile(r"^[A-Za-z]{1,10}\s*\d{1,3}$")))
async def prefixed(message: Message):
    tup = parse_code_token(message.text or "")
    if not tup:
        await message.answer("Exemple: l10, f105, c7, m3, fo70, t75.")
        return
    code, num = tup
    user_brand[message.from_user.id] = code
    await show_item(message, code, num)

# doar număr => folosește brandul curent (default Linella)
@router.message(F.text.regexp(re.compile(r"^\d{1,3}$")))
async def only_number(message: Message):
    code = user_brand.get(message.from_user.id, "l")
    await show_item(message, code, int((message.text or "").strip()))

# ─────────────────────────────────────────────────────────
# Cale optimă
# ─────────────────────────────────────────────────────────
@router.message(F.text == "🧭 Cale optimă")
async def ask_route_mode(message: Message):
    await message.answer("Alege modul pentru rută optimă:", reply_markup=route_mode_kb())

@router.callback_query(F.data == "route:loc")
async def route_from_location(cb: CallbackQuery):
    user_route_mode[cb.from_user.id] = "loc"
    await cb.answer()
    loc = user_location.get(cb.from_user.id)
    if loc:
        await cb.message.answer(
            f"📍 Origine: {loc[0]:.6f}, {loc[1]:.6f}\nTrimite lista (ex: l5 c30 fo70).",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await cb.message.answer(
            "Trimite lista de magazine (ex: l5 c30 fo70).\n"
            "Originea va fi locația ta (apasă întâi „📍 Trimite locația mea”).",
            reply_markup=ReplyKeyboardRemove(),
        )

@router.callback_query(F.data == "route:first")
async def route_from_first(cb: CallbackQuery):
    user_route_mode[cb.from_user.id] = "first"
    await cb.answer()
    await cb.message.answer(
        "Trimite lista de magazine (ex: l5 c30 fo70). Originea va fi **primul magazin** din listă.",
        reply_markup=ReplyKeyboardRemove(),
    )

# Linie cu ≥ 2 coduri: "l5 c30 fo70"
_MULTI_RGX = re.compile(r"(?i)(?:^| )([a-z]{1,10}\s*\d{1,3})(?:[ ,;|]+[a-z]{1,10}\s*\d{1,3})+")

@router.message(F.text.regexp(_MULTI_RGX))
async def route_codes(message: Message):
    await codes_or_route(message)

async def codes_or_route(message: Message):
    print(f"[{now_hms()}] MSG {user_tag(message.from_user)} -> {repr(message.text)}")

    pairs = parse_codes_line(message.text or "")
    if not pairs:
        await message.answer("Format invalid. Exemplu: l5 c30 fo70", reply_markup=main_kb())
        return

    pts: List[Tuple[float, float]] = []
    titles: List[str] = []
    for code, num in pairs:
        d = DATA_BY_BRAND.get(code, {}).get(str(num))
        if not d:
            continue
        lat, lon = float(d.get("lat") or 0), float(d.get("lon") or 0)
        if not lat or not lon:
            continue
        name = BRANDS[code][0]
        address = d.get("address") or ""
        titles.append(f"{name} {num} – {address}")
        pts.append((lat, lon))

    if len(pts) < 2:
        if pts:
            lat, lon = pts[0]
            await message.answer("\n".join(titles), reply_markup=links_kb_single(lat, lon))
            await message.answer_location(latitude=lat, longitude=lon, reply_markup=main_kb())
        else:
            await message.answer("Nu am putut găsi punctele. Verifică codurile (ex: l5 c30 fo70).", reply_markup=main_kb())
        return

    mode = user_route_mode.get(message.from_user.id, "first")
    if mode == "loc":
        origin = user_location.get(message.from_user.id)
        if not origin:
            await message.answer("Trimite mai întâi locația (butonul „📍 Trimite locația mea”).", reply_markup=main_kb())
            return
        points = pts[:]  # toți sunt destinații
    else:
        origin = pts[0]
        points = pts[1:]

    order, total_sec = await directions_optimize(origin, points)

    ordered_pts: List[Tuple[float, float]] = []
    ordered_titles: List[str] = []
    if mode == "loc":
        for i in order:
            ordered_pts.append(points[i])
            ordered_titles.append(titles[i])
    else:
        ordered_pts.append(origin)
        ordered_titles.append(titles[0])
        for idx in order:
            ordered_pts.append(points[idx])
            ordered_titles.append(titles[idx + 1])

    mins = max(1, round(total_sec / 60))
    head = f"🚦 Rută optimizată (trafic actual):\nDurată estimată: ~{mins}m\n\n"
    body = "\n".join(f"{i}. {t}" for i, t in enumerate(ordered_titles, 1))
    await message.answer(head + body, reply_markup=links_kb_route(origin if mode == "loc" else None, ordered_pts))

    lat, lon = ordered_pts[-1]
    await message.answer_location(latitude=lat, longitude=lon, reply_markup=main_kb())

# ─────────────────────────────────────────────────────────
# Catch-all: log (nu răspunde; previne “update not handled”)
# ─────────────────────────────────────────────────────────
@router.message()
async def log_everything(message: Message):
    ctype = getattr(message, "content_type", "unknown")
    if message.text:
        payload = repr(message.text)
    elif message.location:
        payload = f"<location {message.location.latitude:.6f},{message.location.longitude:.6f}>"
    else:
        payload = "<non-text>"
    print(f"[{now_hms()}] MSG {user_tag(message.from_user)} [{ctype}] -> {payload}")
