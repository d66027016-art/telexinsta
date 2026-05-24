import json
from pathlib import Path
import os
import datetime

USERS_FILE = Path(os.getenv("DATA_DIR", ".")) / "users.json"

def load_users():
    if not USERS_FILE.exists():
        return {}
    try:
        with USERS_FILE.open("r") as f:
            data = json.load(f)
            
            # Migrate old string username format to dictionary format
            migrated = False
            for k, v in data.items():
                if isinstance(v, str):
                    data[k] = {
                        "username": v,
                        "coins": 50,
                        "last_reset": datetime.date.today().isoformat()
                    }
                    migrated = True
            if migrated:
                save_users(data)
            return data
    except Exception:
        return {}

def save_users(users):
    with USERS_FILE.open("w") as f:
        json.dump(users, f, indent=4)

def get_user_data(chat_id):
    """Retrieves user profile data, setting default 50 coins and checking monthly resets."""
    users = load_users()
    chat_id = str(chat_id)
    
    if chat_id not in users:
        users[chat_id] = {
            "username": None,
            "coins": 50,
            "last_reset": datetime.date.today().isoformat()
        }
        save_users(users)
    else:
        user = users[chat_id]
        if not isinstance(user, dict):
            # Migrate inline
            user = {
                "username": user,
                "coins": 50,
                "last_reset": datetime.date.today().isoformat()
            }
            users[chat_id] = user
            save_users(users)
        
        # Check monthly reset
        last_reset_str = user.get("last_reset")
        if last_reset_str:
            try:
                last_reset = datetime.date.fromisoformat(last_reset_str)
                today = datetime.date.today()
                # Reset if a new month has started or 30 days have elapsed
                if today.month != last_reset.month or (today - last_reset).days >= 30:
                    user["coins"] = 50
                    user["last_reset"] = today.isoformat()
                    users[chat_id] = user
                    save_users(users)
            except Exception:
                pass
                
    return users[chat_id]

def set_user_instagram(chat_id, username):
    users = load_users()
    chat_id = str(chat_id)
    user_data = get_user_data(chat_id)
    user_data["username"] = username
    users[chat_id] = user_data
    save_users(users)

def get_user_instagram(chat_id):
    user_data = get_user_data(chat_id)
    return user_data.get("username")

def deduct_coin(chat_id):
    """Deduct 1 coin from user balance. Returns True if successful, False if insufficient."""
    users = load_users()
    chat_id = str(chat_id)
    user_data = get_user_data(chat_id)
    current_coins = user_data.get("coins", 50)
    
    if current_coins > 0:
        user_data["coins"] = current_coins - 1
        users[chat_id] = user_data
        save_users(users)
        return True
    return False

def add_coins(chat_id, amount):
    """Adds a specific amount of coins to user's balance."""
    users = load_users()
    chat_id = str(chat_id)
    user_data = get_user_data(chat_id)
    user_data["coins"] = user_data.get("coins", 50) + amount
    users[chat_id] = user_data
    save_users(users)
