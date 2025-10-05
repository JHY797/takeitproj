# server.py — Render Free + FastAPI + Aiogram 3.22 (webhook, folosind bot.py + router)
import os
import logging
import importlib

from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from aiogram.client.default import DefaultBotProperties

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("server")

# === Importă modulul tău principal de bot (NU trebuie să pornească polling la import) ===
bot_module = importlib.import_module("bot")

# 1) BOT — folosim un singur Bot: din env (TELEGRAM_TOKEN pe Render)
TOKEN = os.environ["TELEGRAM_TOKEN"]
bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
log.info("[init] Bot creat din TELEGRAM_TOKEN (env)")

# 2) DP — refolosim dp din bot.py dacă există, altfel creăm și includem router-ele tale
if hasattr(bot_module, "dp") and isinstance(getattr(bot_module, "dp"), Dispatcher):
    dp: Dispatcher = getattr(bot_module, "dp")
    log.info("[import] Folosesc dp din bot.py")
else:
    dp = Dispatcher()
    log.info("[init] Creat Dispatcher nou (dp)")

# 3) Include explicit router-ul din bot.py (OBLIGATORIU ca handlers să fie vizibile)
#    În bot.py ai `router = Router()` -> îl includem aici.
if hasattr(bot_module, "router"):
    try:
        dp.include_router(getattr(bot_module, "router"))
        log.info("[routers] Inclus router din bot.py")
    except Exception as e:
        log.warning(f"[routers] Nu pot include router din bot.py: {e}")
else:
    log.warning("[routers] Nu există `router` în bot.py. (Asigură-te că ai `router = Router()`)")

# === FastAPI + webhook ===
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "changeme")
BASE_URL = os.getenv("BASE_URL") or os.getenv("RENDER_EXTERNAL_URL")

app = FastAPI(title="Telegram Bot Webhook (Render)")

@app.get("/")
async def health():
    # arată ce am inclus, util la debug
    return {"status": "ok", "webhook": f"/webhook/{WEBHOOK_SECRET}", "router_included": hasattr(bot_module, "router")}

@app.on_event("startup")
async def on_startup():
    if BASE_URL:
        url = f"{BASE_URL}/webhook/{WEBHOOK_SECRET}"
        # poți seta allowed_updates ca să ne concentrăm pe ce ai nevoie
        await bot.set_webhook(url, drop_pending_updates=True)
        log.info(f"[startup] set_webhook -> {url}")
    else:
        log.warning("[startup] BASE_URL/RENDER_EXTERNAL_URL lipsește — setează manual setWebhook.")

@app.on_event("shutdown")
async def on_shutdown():
    try:
        await bot.delete_webhook()
        log.info("[shutdown] delete_webhook OK")
    except Exception as e:
        log.warning(f"[shutdown] delete_webhook err: {e}")

@app.post("/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request):
    if secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="bad secret")
    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}
