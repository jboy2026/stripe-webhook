import os
import sqlite3
from datetime import datetime, timezone

import stripe
from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

# -----------------------------
# Config
# -----------------------------
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
DB_PATH = os.getenv("DB_PATH", "payments.db")

if not STRIPE_SECRET_KEY:
    raise RuntimeError("Missing STRIPE_SECRET_KEY in environment")
# STRIPE_WEBHOOK_SECRET is allowed to be missing at startup

stripe.api_key = STRIPE_SECRET_KEY

# -----------------------------
# Database
# -----------------------------
def db_connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

db = db_connect()

db.execute("""
    CREATE TABLE IF NOT EXISTS role_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        discord_user_id TEXT NOT NULL,
        action TEXT NOT NULL,
        reason TEXT,
        created_at_utc TEXT NOT NULL,
        done INTEGER NOT NULL DEFAULT 0
    )
""")
db.commit()

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def enqueue_job(discord_user_id: str, action: str, reason: str):
    db.execute("""
        INSERT INTO role_jobs(discord_user_id, action, reason, created_at_utc)
        VALUES(?,?,?,?)
    """, (discord_user_id, action, reason, utc_now()))
    db.commit()

# -----------------------------
# FastAPI app
# -----------------------------
app = FastAPI()

@app.post("/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=stripe_signature,
            secret=STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    etype = event["type"]
    obj = event["data"]["object"]

    if etype == "checkout.session.completed":
        discord_user_id = obj.get("client_reference_id")
        if discord_user_id:
            enqueue_job(discord_user_id, "grant", etype)

    elif etype in ("invoice.payment_failed", "customer.subscription.deleted"):
        customer = obj.get("customer")
        if customer:
            # In production you'd map customer → discord ID
            # If you later want this, we can expand it cleanly
            pass


    return {"ok": True}
