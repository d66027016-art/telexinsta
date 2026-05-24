import json
import random
import string
from pathlib import Path
import os
import datetime
from user_manager import add_coins, get_user_data

CODES_FILE = Path(os.getenv("DATA_DIR", ".")) / "redeem_codes.json"

def load_codes():
    if not CODES_FILE.exists():
        return {}
    try:
        with CODES_FILE.open("r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_codes(codes):
    with CODES_FILE.open("w") as f:
        json.dump(codes, f, indent=4)

def generate_random_code(length=12):
    """Generates a random code like VEO-XXXX-XXXX"""
    chars = string.ascii_uppercase + string.digits
    part1 = "".join(random.choices(chars, k=4))
    part2 = "".join(random.choices(chars, k=4))
    return f"VEO-{part1}-{part2}"

def parse_duration(duration_str: str):
    """
    Parses duration string like '1d', '2h', '30m' into a datetime object.
    Returns datetime or raises ValueError.
    """
    if not duration_str or duration_str.lower() in ["none", "null", "-"]:
        return None
    
    duration_str = duration_str.strip().lower()
    now = datetime.datetime.now()
    
    try:
        if duration_str.endswith("d"):
            days = float(duration_str[:-1])
            return now + datetime.timedelta(days=days)
        elif duration_str.endswith("h"):
            hours = float(duration_str[:-1])
            return now + datetime.timedelta(hours=hours)
        elif duration_str.endswith("m"):
            minutes = float(duration_str[:-1])
            return now + datetime.timedelta(minutes=minutes)
        else:
            # Default to days if just a number
            days = float(duration_str)
            return now + datetime.timedelta(days=days)
    except ValueError:
        raise ValueError("Invalid expiry format. Use e.g., 5d (days), 12h (hours), 30m (minutes) or a number of days.")

def create_redeem_code(coins: int, max_uses: int = 1, custom_code: str = None, expiry_duration: str = None):
    """
    Creates a redeem code.
    If custom_code is provided, uses it (uppercased). Otherwise generates a random one.
    """
    codes = load_codes()
    
    if custom_code and custom_code.lower() not in ["none", "null", "-"]:
        code = custom_code.strip().upper()
    else:
        code = None
        
    if not code:
        # Generate a unique random code
        while True:
            code = generate_random_code()
            if code not in codes:
                break
                
    if code in codes:
        raise ValueError(f"Code '{code}' already exists.")
        
    expires_at = None
    if expiry_duration:
        expires_dt = parse_duration(expiry_duration)
        if expires_dt:
            expires_at = expires_dt.isoformat()
            
    codes[code] = {
        "coins": coins,
        "max_uses": max_uses,
        "used_by": [],
        "created_at": datetime.datetime.now().isoformat(),
        "expires_at": expires_at
    }
    save_codes(codes)
    return code, coins, max_uses, expires_at

def redeem_code(chat_id, code_str: str):
    """
    Redeems a code for a user.
    Returns:
        dict: {"success": bool, "message": str, "coins": int (optional), "new_balance": int (optional)}
    """
    chat_id = str(chat_id)
    code = code_str.strip().upper()
    
    codes = load_codes()
    if code not in codes:
        return {"success": False, "message": "❌ Invalid redeem code. Please double check the code."}
        
    code_data = codes[code]
    
    # Check if expired
    expires_at_str = code_data.get("expires_at")
    if expires_at_str:
        try:
            expires_at = datetime.datetime.fromisoformat(expires_at_str)
            if datetime.datetime.now() > expires_at:
                return {"success": False, "message": "❌ This code has expired."}
        except Exception:
            pass
            
    # Check if user already used this code
    if chat_id in code_data.get("used_by", []):
        return {"success": False, "message": "❌ You have already redeemed this code!"}
        
    # Check if max uses reached
    max_uses = code_data.get("max_uses", 1)
    used_by = code_data.get("used_by", [])
    if len(used_by) >= max_uses:
        return {"success": False, "message": "❌ This code has reached its maximum usage limit."}
        
    # Valid code! Redeem it.
    coins_to_add = code_data.get("coins", 0)
    used_by.append(chat_id)
    code_data["used_by"] = used_by
    codes[code] = code_data
    save_codes(codes)
    
    # Add coins to the user
    add_coins(chat_id, coins_to_add)
    
    # Get new balance
    user_data = get_user_data(chat_id)
    new_balance = user_data.get("coins", 50)
    
    return {
        "success": True,
        "message": f"🎉 **Code Redeemed Successfully!**\n🎁 Added `{coins_to_add}` coins to your balance.",
        "coins": coins_to_add,
        "new_balance": new_balance
    }

def list_active_codes():
    """Lists all codes that haven't reached their usage limit and haven't expired."""
    codes = load_codes()
    active = {}
    now = datetime.datetime.now()
    for code, data in codes.items():
        max_uses = data.get("max_uses", 1)
        used_count = len(data.get("used_by", []))
        
        expired = False
        expires_at_str = data.get("expires_at")
        if expires_at_str:
            try:
                expires_at = datetime.datetime.fromisoformat(expires_at_str)
                if now > expires_at:
                    expired = True
            except Exception:
                pass
                
        if used_count < max_uses and not expired:
            active[code] = data
    return active

def revoke_code(code_str: str):
    """Deletes/revokes a code."""
    code = code_str.strip().upper()
    codes = load_codes()
    if code in codes:
        del codes[code]
        save_codes(codes)
        return True
    return False
