# server.py — Aiogram 3.22 + FastAPI (Render webhook)
import os
import logging
from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Update

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("server")

# 1) Bot unic creat aici din env
TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN lipsește în Environment (Render).")
bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode="HTML"))

# 2) Dispatcher + router din bot.py (bot.py NU creează Bot la import)
from bot import router as bot_router
dp = Dispatcher()
dp.include_router(bot_router)
log.info("[routers] Inclus router din bot.py ✅")

# 3) FastAPI + webhook
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "changeme")
BASE_URL = os.getenv("BASE_URL") or os.getenv("RENDER_EXTERNAL_URL")

app = FastAPI(title="Telegram Bot Webhook (Render)")

@app.get("/")
async def health():
    return {
        "status": "ok",
        "webhook": f"/webhook/{WEBHOOK_SECRET}",
        "router_included": True,
    }

@app.on_event("startup")
async def on_startup():
    if BASE_URL:
        url = f"{BASE_URL}/webhook/{WEBHOOK_SECRET}"
        await bot.set_webhook(url, drop_pending_updates=True)
        log.info(f"[startup] set_webhook -> {url}")
    else:
        log.warning("[startup] BASE_URL/RENDER_EXTERNAL_URL lipsește — setează manual setWebhook din browser.")

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
