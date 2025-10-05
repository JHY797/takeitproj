# Integrare Render (Free) — Webhook adapter

**Versiune aiogram detectată:** v3
- `dp` găsit în: None
- `bot` găsit în: None

## Pași
1) Copiază `server.py` în rădăcina proiectului tău.
2) Asigură-te că în `requirements.txt` ai `fastapi` și `uvicorn[standard]`; dacă nu, adaugă:
   - `fastapi>=0.110,<0.121`
   - `uvicorn[standard]>=0.29,<0.33`
3) Pe Render:
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn server:app --host 0.0.0.0 --port $PORT`
   - Env vars: `TELEGRAM_TOKEN`, `WEBHOOK_SECRET` (+ opțional `BASE_URL`)
4) La startup se setează automat webhook-ul către `https://<domeniu>/webhook/<WEBHOOK_SECRET>`.
5) Dacă nu se setează: rulează manual setWebhook în browser.

## Notă
- Nu mai porni `start_polling` pe Render.
- Handlerii existenți rămân neschimbați; `server.py` doar le livrează update-urile.
