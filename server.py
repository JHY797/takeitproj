# server.py — Render Free + FastAPI + Aiogram 3.22 (webhook)
import os
import logging
import importlib
import pkgutil
from typing import List

from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from aiogram.client.default import DefaultBotProperties

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("server")

# ========== 1) Încearcă să reutilizezi bot/dp din proiect ==========
bot = None
dp = None

# Încearcă diverse locații comune din proiectul tău — adaugă aici dacă e altă cale.
CANDIDATE_IMPORTS = [
    # ("modul", "nume_atribut")
    ("bot", "bot"),            # ex: in bot.py -> bot = Bot(...)
    ("bot", "dp"),             # ex: in bot.py -> dp = Dispatcher()
    ("core.bot", "bot"),
    ("core.dispatcher", "dp"),
    ("app.bot", "bot"),
    ("app.dispatcher", "dp"),
]

for modname, attr in CANDIDATE_IMPORTS:
    try:
        mod = importlib.import_module(modname)
        val = getattr(mod, attr)
        if attr == "bot":
            bot = val
            log.info(f"[import] Refolosesc bot din {modname}.{attr}")
        elif attr == "dp":
            dp = val
            log.info(f"[import] Refolosesc dp din {modname}.{attr}")
    except Exception:
        pass  # nu e o problemă dacă nu există; avem fallback mai jos

# Dacă nu există, creăm instanțele
if bot is None:
    TOKEN = os.environ["TELEGRAM_TOKEN"]
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    log.info("[init] Creat bot din TELEGRAM_TOKEN (env)")

if dp is None:
    dp = Dispatcher()
    log.info("[init] Creat Dispatcher implicit (dp)")

# ========== 2) Include automat router-ele (handlers) dacă există ==========
def include_all_routers(dp: Dispatcher) -> List[str]:
    """
    Caută pachete handlers și include automat orice `router` găsit în submodule.
    Acceptă denumiri tipice: handlers, app.handlers, src.handlers.
    Returnează lista modulelor în care a găsit router.
    """
    found_in = []
    candidate_pkgs = ["handlers", "app.handlers", "src.handlers"]

    for pkg_name in candidate_pkgs:
        try:
            pkg = importlib.import_module(pkg_name)
        except Exception:
            continue  # pachetul nu există

        # Parcurge recursiv submodulele pachetului
        if hasattr(pkg, "__path__"):
            for finder, name, ispkg in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
                try:
                    mod = importlib.import_module(name)
                    # dacă modulul expune obiectul `router`, îl includem
                    router = getattr(mod, "router", None)
                    if router is not None:
                        dp.include_router(router)
                        found_in.append(name)
                        log.info(f"[routers] Inclus router din {name}")
                except Exception as e:
                    log.warning(f"[routers] Nu pot importa {name}: {e}")
        else:
            # pachet unic (puțin probabil)
            router = getattr(pkg, "router", None)
            if router is not None:
                dp.include_router(router)
                found_in.append(pkg_name)
                log.info(f"[routers] Inclus router din {pkg_name}")

    return found_in

# (opțional) încearcă să incluzi automat router-ele
included_modules = include_all_routers(dp)
if not included_modules:
    log.info("[routers] Nu am găsit pachet de handlers. Dacă ai handlers, asigură-te că există un pachet "
             "`handlers/` (sau `app/handlers`, `src/handlers`) și că fiecare modul expune `router = Router()`.")

# ========== 3) FastAPI app + webhook ==========
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "changeme")
BASE_URL = os.getenv("BASE_URL") or os.getenv("RENDER_EXTERNAL_URL")

app = FastAPI(title="Telegram Bot Webhook (Render)")

@app.get("/")
async def health():
    return {
        "status": "ok",
        "webhook": f"/webhook/{WEBHOOK_SECRET}",
        "routers": included_modules,
    }

@app.on_event("startup")
async def on_startup():
    # La startup, setează webhook (dacă avem URL public disponibil)
    if BASE_URL:
        url = f"{BASE_URL}/webhook/{WEBHOOK_SECRET}"
        await bot.set_webhook(url, drop_pending_updates=True)
        log.info(f"[startup] set_webhook -> {url}")
    else:
        log.warning("[startup] BASE_URL/RENDER_EXTERNAL_URL lipsește — poți seta manual setWebhook din browser.")

@app.on_event("shutdown")
async def on_shutdown():
    try:
        await bot.delete_webhook()
        log.info("[shutdown] delete_webhook OK")
    except Exception as e:
        log.warning(f"[shutdown] delete_webhook err: {e}")

@app.post("/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request):
    # Securizăm endpoint-ul cu un token secret în URL
    if secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="bad secret")
    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}
