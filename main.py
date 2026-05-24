import logging
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from instagram_client import get_client
from telegram_bot import bot_manager, send_telegram_notification
from config_manager import load_config, save_config
from user_manager import get_user_data, deduct_coin

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Request models
class LoginRequest(BaseModel):
    username: str
    password: str
    verification_code: Optional[str] = None

class ScrapeRequest(BaseModel):
    target_username: str
    amount: Optional[int] = 12

class RepostRequest(BaseModel):
    media_id: str
    custom_caption: Optional[str] = None

class ConfigRequest(BaseModel):
    telegram_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_notifications_enabled: Optional[bool] = None
    telegram_bot_enabled: Optional[bool] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start the Telegram Bot if configurations exist and bot is enabled
    config = load_config()
    if config.get("telegram_bot_enabled", True) and config.get("telegram_token"):
        logger.info("Initializing Telegram Bot on startup...")
        bot_manager.start()
    yield
    # Shutdown: Stop the Telegram Bot to clean up threads
    logger.info("Shutting down Telegram Bot...")
    bot_manager.stop()

app = FastAPI(
    title="Instagram Auto-Reposter & Telegram Hub",
    description="Backend API to scrape Instagram media, manage configurations, and trigger reposting.",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes

def get_admin_client():
    config = load_config()
    chat_id = config.get("telegram_chat_id") or "admin"
    return get_client(chat_id)

@app.get("/api/status")
async def get_status():
    """Returns the current state of Instagram session and Telegram Bot."""
    config = load_config()
    
    # Mask Telegram token for safety in UI
    raw_token = config.get("telegram_token", "")
    masked_token = ""
    if raw_token:
        if len(raw_token) > 10:
            masked_token = f"{raw_token[:6]}...{raw_token[-4:]}"
        else:
            masked_token = "********"

    admin_client = get_admin_client()

    return {
        "instagram_logged_in": admin_client.logged_in,
        "instagram_username": admin_client.current_username,
        "telegram_token_configured": bool(raw_token),
        "telegram_token_masked": masked_token,
        "telegram_chat_id": config.get("telegram_chat_id", ""),
        "telegram_notifications_enabled": config.get("telegram_notifications_enabled", True),
        "telegram_bot_enabled": config.get("telegram_bot_enabled", True),
        "telegram_bot_running": bot_manager.running
    }

@app.post("/api/config")
async def update_config(req: ConfigRequest):
    """Updates system configurations and restarts the Telegram Bot dynamically."""
    current_config = load_config()
    
    # Prepare updates
    updates = {}
    if req.telegram_token is not None:
        updates["telegram_token"] = req.telegram_token
    if req.telegram_chat_id is not None:
        updates["telegram_chat_id"] = req.telegram_chat_id
    if req.telegram_notifications_enabled is not None:
        updates["telegram_notifications_enabled"] = req.telegram_notifications_enabled
    if req.telegram_bot_enabled is not None:
        updates["telegram_bot_enabled"] = req.telegram_bot_enabled

    # Save
    if save_config(updates):
        # Restart or stop bot based on new config
        config = load_config()
        if config.get("telegram_bot_enabled") and config.get("telegram_token"):
            bot_manager.start()
        else:
            bot_manager.stop()
        
        return {"status": "success", "config": config}
    else:
        raise HTTPException(status_code=500, detail="Failed to save configuration.")

@app.post("/api/login")
def login_instagram(req: LoginRequest):
    """Logs in to the user's Instagram account."""
    admin_client = get_admin_client()
    res = admin_client.login(req.username, req.password, req.verification_code)
    
    if res["status"] == "success":
        send_telegram_notification(f"🔔 **Instagram logged in successfully** as `{req.username}`!")
        return res
    elif res["status"] in ["two_factor_required", "challenge_required"]:
        return res
    else:
        raise HTTPException(status_code=400, detail=res["message"])

@app.post("/api/logout")
def logout_instagram():
    """Logs out of Instagram and destroys session files."""
    admin_client = get_admin_client()
    res = admin_client.logout()
    if res["status"] == "success":
        send_telegram_notification("📴 **Instagram logged out** from the web dashboard.")
        return res
    else:
        raise HTTPException(status_code=400, detail="Logout failed.")

@app.post("/api/scrape")
def scrape_profile(req: ScrapeRequest):
    """Scrapes posts and reels from a target username."""
    admin_client = get_admin_client()
    if not admin_client.logged_in:
        raise HTTPException(status_code=401, detail="Instagram is not logged in. Please log in first.")
    
    try:
        medias = admin_client.get_profile_medias(req.target_username, req.amount)
        return {"status": "success", "medias": medias}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch profile: {str(e)}")

@app.post("/api/repost")
def repost_media(req: RepostRequest):
    """Downloads and reposts a single media item to your Instagram feed."""
    config = load_config()
    chat_id = config.get("telegram_chat_id") or "admin"
    
    # Check coin balance
    user_data = get_user_data(chat_id)
    if user_data.get("coins", 0) <= 0:
        raise HTTPException(
            status_code=403, 
            detail="Insufficient Coins! You have 0 coins left. Monthly coins will reset next month."
        )
        
    admin_client = get_admin_client()
    if not admin_client.logged_in:
        raise HTTPException(status_code=401, detail="Instagram is not logged in.")
    
    if getattr(bot_manager, "global_stop", False):
        raise HTTPException(status_code=400, detail="Task stopped via Telegram command.")
    
    try:
        # Repost
        result = admin_client.repost_media(req.media_id, req.custom_caption)
        
        # Deduct a coin
        deduct_coin(chat_id)
        remaining_coins = get_user_data(chat_id).get("coins", 50)
        
        # Send Telegram notification
        send_telegram_notification(
            f"📤 **Instagram Repost Success!**\n"
            f"• Type: `{result['type'].upper()}`\n"
            f"• Original Media ID: `{req.media_id}`\n"
            f"• New Media PK: `{result['new_pk']}`\n"
            f"🪙 **Coins remaining:** `{remaining_coins}`\n"
            f"🗑️ _Video/Photo was instantly deleted from the server to save space._"
        )
        
        result["remaining_coins"] = remaining_coins
        return result
    except Exception as e:
        logger.error(f"Repost failed for media ID {req.media_id}: {e}")
        send_telegram_notification(
            f"❌ **Instagram Repost Failed!**\n"
            f"• Original Media ID: `{req.media_id}`\n"
            f"• Error: `{str(e)}`"
        )
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/clear_stop")
def clear_stop_flag():
    """Clears the global stop flag to allow new tasks."""
    bot_manager.global_stop = False
    return {"status": "success", "message": "Stop flag cleared."}


# HTML serving logic
@app.get("/")
async def get_index():
    """Serves the static index.html entry point."""
    return FileResponse("static/index.html")

# Mount the static files directory containing index.html, style.css, app.js
app.mount("/static", StaticFiles(directory="static"), name="static")
