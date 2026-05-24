import time
import datetime
import logging
import threading
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from config_manager import load_config, save_config
from instagram_client import get_client, SESSIONS_DIR
from user_manager import get_user_data, deduct_coin, add_coins
from redeem_manager import create_redeem_code, redeem_code, list_active_codes, revoke_code

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TelegramBotManager:
    def __init__(self):
        self.bot = None
        self.thread = None
        self.running = False
        self.token = None
        self.stop_flags = {}
        self.global_stop = False

    def start(self):
        """Starts the Telegram Bot in a background thread if token is present."""
        config = load_config()
        token = config.get("telegram_token")
        
        if not token:
            logger.info("Telegram Bot Token is not set. Bot remains offline.")
            return False

        if self.running:
            if self.token == token:
                logger.info("Telegram Bot is already running with the current token.")
                return True
            else:
                logger.info("Telegram Bot Token changed. Restarting bot...")
                self.stop()

        try:
            self.token = token
            self.bot = telebot.TeleBot(token)
            self.setup_handlers()
            
            self.running = True
            self.thread = threading.Thread(target=self._run_bot, daemon=True)
            self.thread.start()
            logger.info("Telegram Bot background thread started.")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Telegram Bot: {e}")
            self.running = False
            self.bot = None
            self.thread = None
            return False

    def stop(self):
        """Stops the Telegram Bot polling and background thread."""
        if not self.running:
            return
        
        logger.info("Stopping Telegram Bot...")
        self.running = False
        if self.bot:
            try:
                self.bot.stop_polling()
            except Exception as e:
                logger.error(f"Error stopping bot polling: {e}")
        
        if self.thread:
            self.thread.join(timeout=2)
        
        self.bot = None
        self.thread = None
        logger.info("Telegram Bot stopped.")

    def _run_bot(self):
        """Internal polling loop."""
        while self.running:
            try:
                logger.info("Telegram Bot polling started.")
                self.bot.infinity_polling(timeout=10, long_polling_timeout=5)
            except Exception as e:
                logger.error(f"Telegram Bot error during polling: {e}")
                time.sleep(5)  # Wait before retrying to prevent hot looping

    def setup_handlers(self):
        """Registers handlers for commands, messages, and callback queries."""
        
        @self.bot.message_handler(commands=['start', 'help'])
        def send_welcome(message):
            welcome_text = (
                "👋 **Welcome to Instagram Reposter Bot BY @DAMXD89!**\n\n"
                "To get started, you need to connect your Instagram account.\n"
                "Please send the following command:\n"
                "`/login <your_username> <your_password>`\n\n"
                "After logging in, send me any Instagram username or profile URL "
                "(e.g. `@cristiano` or `https://instagram.com/cristiano`), "
                "and I will fetch their recent posts/reels so you can repost them!"
            )
            
            markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
            markup.row(KeyboardButton('📊 Status'), KeyboardButton('❓ Help'))
            
            self.bot.reply_to(message, welcome_text, parse_mode="Markdown", reply_markup=markup)

        @self.bot.message_handler(commands=['login'])
        def handle_login(message):
            chat_id = message.chat.id
            parts = message.text.strip().split()
            if len(parts) < 3:
                self.bot.reply_to(message, "❌ **Usage:** `/login <username> <password>`", parse_mode="Markdown")
                return
            
            username = parts[1]
            password = parts[2]
            
            status_msg = self.bot.reply_to(message, "⏳ Logging into Instagram... Please wait.")
            
            client = get_client(chat_id)
            res = client.login(username, password)
            
            if res.get("status") == "success":
                self.bot.edit_message_text(
                    f"✅ **Successfully logged in as `{username}`!**\n"
                    f"You can now send any target username to fetch posts.- username <x>\n"
                    f"x is no of post and reels",
                    chat_id=chat_id,
                    message_id=status_msg.message_id,
                    parse_mode="Markdown"
                )
            else:
                error_msg = res.get("message", "Unknown error")
                self.bot.edit_message_text(
                    f"❌ **Login failed:** {error_msg}",
                    chat_id=chat_id,
                    message_id=status_msg.message_id,
                    parse_mode="Markdown"
                )

        @self.bot.message_handler(commands=['stop'])
        def handle_stop(message):
            chat_id = message.chat.id
            self.stop_flags[chat_id] = True
            self.global_stop = True
            self.bot.reply_to(message, "🛑 Stop command received. Stopping ongoing tasks...")

        def is_admin(chat_id):
            config = load_config()
            admin_chat_id = config.get("telegram_chat_id")
            return str(chat_id) == str(admin_chat_id)

        @self.bot.message_handler(commands=['admin'])
        def handle_admin_help(message):
            if not is_admin(message.chat.id):
                self.bot.reply_to(message, "❌ **Access Denied:** Only the bot owner/admin can use this command.")
                return
            
            help_text = (
                "👑 **Admin Command Panel:**\n\n"
                "• `/broadcast <message>` - Broadcast a message to all users.\n"
                "• `/users` - List all registered users, IG handles, and coin balances.\n"
                "• `/addcoins <chat_id> <amount>` - Add coins to a specific user.\n"
                "• `/setcoins <chat_id> <amount>` - Set exact coin balance for a user.\n"
                "• `/gencode <coins> [max_uses] [custom_code] [expiry]` - Generate a redeem code.\n"
                "• `/activecodes` - List all active redeem codes.\n"
                "• `/revoke <code>` - Revoke/delete a redeem code."
            )
            self.bot.reply_to(message, help_text, parse_mode="Markdown")

        @self.bot.message_handler(commands=['broadcast'])
        def handle_broadcast(message):
            if not is_admin(message.chat.id):
                self.bot.reply_to(message, "❌ **Access Denied.**")
                return
            
            parts = message.text.split(maxsplit=1)
            if len(parts) < 2:
                self.bot.reply_to(message, "❌ **Usage:** `/broadcast <your message>`", parse_mode="Markdown")
                return
            
            broadcast_text = parts[1]
            status_msg = self.bot.reply_to(message, "📢 **Initializing broadcast...**", parse_mode="Markdown")
            
            from user_manager import load_users
            users = load_users()
            total = len(users)
            success = 0
            failed = 0
            
            for target_chat_id in users.keys():
                try:
                    self.bot.send_message(
                        target_chat_id, 
                        f"📢 **Announcement from Admin:**\n\n{broadcast_text}", 
                        parse_mode="Markdown"
                    )
                    success += 1
                except Exception as e:
                    logger.error(f"Failed to send broadcast to {target_chat_id}: {e}")
                    failed += 1
            
            self.bot.edit_message_text(
                f"📢 **Broadcast Complete!**\n\n"
                f"• Total registered: `{total}`\n"
                f"• Sent successfully: `{success}`\n"
                f"• Failed/Blocked: `{failed}`",
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                parse_mode="Markdown"
            )

        @self.bot.message_handler(commands=['users'])
        def handle_list_users(message):
            if not is_admin(message.chat.id):
                self.bot.reply_to(message, "❌ **Access Denied.**")
                return
            
            from user_manager import load_users, get_user_data
            users = load_users()
            if not users:
                self.bot.reply_to(message, "📭 No registered users found.")
                return
            
            lines = ["👥 **Registered Users List:**\n"]
            for chat_id in users.keys():
                user_data = get_user_data(chat_id)
                username = user_data.get("username") or "None"
                coins = user_data.get("coins", 50)
                lines.append(f"• `{chat_id}`: @{username} (🪙 `{coins}` coins)")
            
            response_text = "\n".join(lines)
            if len(response_text) > 4096:
                for x in range(0, len(response_text), 4096):
                    self.bot.send_message(message.chat.id, response_text[x:x+4096], parse_mode="Markdown")
            else:
                self.bot.reply_to(message, response_text, parse_mode="Markdown")

        @self.bot.message_handler(commands=['addcoins'])
        def handle_add_coins(message):
            if not is_admin(message.chat.id):
                self.bot.reply_to(message, "❌ **Access Denied.**")
                return
            
            parts = message.text.strip().split()
            if len(parts) < 3:
                self.bot.reply_to(message, "❌ **Usage:** `/addcoins <chat_id> <amount>`", parse_mode="Markdown")
                return
            
            target_chat_id = parts[1]
            try:
                amount = int(parts[2])
            except ValueError:
                self.bot.reply_to(message, "❌ **Amount must be an integer.**", parse_mode="Markdown")
                return
            
            add_coins(target_chat_id, amount)
            new_coins = get_user_data(target_chat_id).get("coins", 50)
            
            self.bot.reply_to(
                message, 
                f"✅ Added `{amount}` coins to user `{target_chat_id}`.\n🪙 **New Balance:** `{new_coins}` coins.",
                parse_mode="Markdown"
            )
            try:
                self.bot.send_message(
                    target_chat_id,
                    f"🎁 **Coins Added!**\nAdmin added `{amount}` coins to your balance.\n🪙 **Current Balance:** `{new_coins}` coins.",
                    parse_mode="Markdown"
                )
            except:
                pass

        @self.bot.message_handler(commands=['setcoins'])
        def handle_set_coins(message):
            if not is_admin(message.chat.id):
                self.bot.reply_to(message, "❌ **Access Denied.**")
                return
            
            parts = message.text.strip().split()
            if len(parts) < 3:
                self.bot.reply_to(message, "❌ **Usage:** `/setcoins <chat_id> <amount>`", parse_mode="Markdown")
                return
            
            target_chat_id = parts[1]
            try:
                amount = int(parts[2])
            except ValueError:
                self.bot.reply_to(message, "❌ **Amount must be an integer.**", parse_mode="Markdown")
                return
            
            from user_manager import load_users, save_users
            users = load_users()
            user_data = get_user_data(target_chat_id)
            user_data["coins"] = amount
            users[str(target_chat_id)] = user_data
            save_users(users)
            
            self.bot.reply_to(
                message, 
                f"✅ Set user `{target_chat_id}` balance to `{amount}` coins.",
                parse_mode="Markdown"
            )
            try:
                self.bot.send_message(
                    target_chat_id,
                    f"⚙️ **Coin Balance Updated!**\nAdmin set your balance to `{amount}` coins.\n🪙 **Current Balance:** `{amount}` coins.",
                    parse_mode="Markdown"
                )
            except:
                pass

        @self.bot.message_handler(commands=['gencode'])
        def handle_gencode(message):
            if not is_admin(message.chat.id):
                self.bot.reply_to(message, "❌ **Access Denied.**")
                return
            
            parts = message.text.strip().split()
            if len(parts) < 2:
                self.bot.reply_to(
                    message, 
                    "❌ **Usage:** `/gencode <coins> [max_uses] [custom_code] [expiry_duration]`\n"
                    "_Example:_ `/gencode 50 10 WELCOME 2d` (valid for 2 days. Durations can be e.g., `2d`, `12h`, `30m` or `-` for none)",
                    parse_mode="Markdown"
                )
                return
            
            try:
                coins = int(parts[1])
            except ValueError:
                self.bot.reply_to(message, "❌ **Coins must be an integer.**", parse_mode="Markdown")
                return
                
            max_uses = 1
            if len(parts) > 2:
                try:
                    max_uses = int(parts[2])
                except ValueError:
                    self.bot.reply_to(message, "❌ **Max uses must be an integer.**", parse_mode="Markdown")
                    return
            
            custom_code = None
            if len(parts) > 3:
                custom_code = parts[3]
                
            expiry_duration = None
            if len(parts) > 4:
                expiry_duration = parts[4]
                
            try:
                code, coins, max_uses, expires_at = create_redeem_code(coins, max_uses, custom_code, expiry_duration)
                
                expiry_text = "None"
                if expires_at:
                    try:
                        dt = datetime.datetime.fromisoformat(expires_at)
                        expiry_text = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except:
                        expiry_text = expires_at

                self.bot.reply_to(
                    message,
                    f"🎁 **Redeem Code Created!**\n\n"
                    f"• Code: `{code}`\n"
                    f"• Coins: `{coins}`\n"
                    f"• Max Uses: `{max_uses}`\n"
                    f"• Expires At: `{expiry_text}`\n\n"
                    f"Share this code with users. They can redeem it using `/redeem {code}`",
                    parse_mode="Markdown"
                )
            except Exception as e:
                self.bot.reply_to(message, f"❌ **Failed to create code:** {str(e)}", parse_mode="Markdown")

        @self.bot.message_handler(commands=['activecodes'])
        def handle_activecodes(message):
            if not is_admin(message.chat.id):
                self.bot.reply_to(message, "❌ **Access Denied.**")
                return
                
            active = list_active_codes()
            if not active:
                self.bot.reply_to(message, "📭 No active redeem codes found.")
                return
                
            lines = ["🎁 **Active Redeem Codes:**\n"]
            for code, data in active.items():
                coins = data.get("coins")
                max_uses = data.get("max_uses", 1)
                used_count = len(data.get("used_by", []))
                lines.append(f"• `{code}`: `{coins}` coins (Used: `{used_count}/{max_uses}`)")
                
            self.bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")

        @self.bot.message_handler(commands=['revoke'])
        def handle_revoke(message):
            if not is_admin(message.chat.id):
                self.bot.reply_to(message, "❌ **Access Denied.**")
                return
                
            parts = message.text.strip().split()
            if len(parts) < 2:
                self.bot.reply_to(message, "❌ **Usage:** `/revoke <code>`", parse_mode="Markdown")
                return
                
            code = parts[1]
            if revoke_code(code):
                self.bot.reply_to(message, f"✅ Code `{code.upper()}` has been revoked/deleted.", parse_mode="Markdown")
            else:
                self.bot.reply_to(message, f"❌ Code `{code.upper()}` not found.", parse_mode="Markdown")

        @self.bot.message_handler(commands=['redeem'])
        def handle_redeem(message):
            parts = message.text.strip().split()
            if len(parts) < 2:
                self.bot.reply_to(message, "❌ **Usage:** `/redeem <code>`", parse_mode="Markdown")
                return
                
            code = parts[1]
            res = redeem_code(message.chat.id, code)
            
            if res["success"]:
                self.bot.reply_to(
                    message,
                    f"{res['message']}\n🪙 **New Balance:** `{res['new_balance']}` coins.",
                    parse_mode="Markdown"
                )
            else:
                self.bot.reply_to(message, res["message"], parse_mode="Markdown")

        @self.bot.message_handler(func=lambda message: message.text in ['📊 Status', '❓ Help'])
        def handle_menu_options(message):
            client = get_client(message.chat.id)
            if message.text == '📊 Status':
                user_data = get_user_data(message.chat.id)
                status_text = (
                    "⚙️ **System Status:**\n"
                    f"• Instagram Logged In: `{'Yes' if client.logged_in else 'No'}`\n"
                    f"• Current IG Account: `{client.current_username or 'None'}`\n"
                    f"🪙 **Remaining Coins:** `{user_data.get('coins', 50)} / 50`"
                )
                self.bot.reply_to(message, status_text, parse_mode="Markdown")
            elif message.text == '❓ Help':
                help_text = (
                    "ℹ️ **How to use this bot:**\n"
                    "1. Connect your account using `/login <username> <password>`.\n"
                    "   *Alternative:* If login fails due to security blocks, you can upload/send your local session `.json` file directly to this chat!\n"
                    "2. Send any Instagram username (e.g. `cristiano`) to me.\n"
                    "3. I will show you their latest posts/reels. By default, I fetch 10 posts.\n"
                    "   *Tip:* You can specify the number of posts to fetch by sending `username amount` (e.g. `cristiano 20`).\n"
                    "4. Click '📤 Repost to Instagram' below any post to repost it to your feed.\n"
                    "🪙 **Coin Limit:** Each repost costs `1` coin. You get `50` free coins every month!\n"
                    "🎁 Have a redeem code? Use `/redeem <code>` to add more coins to your account."
                )
                self.bot.reply_to(message, help_text, parse_mode="Markdown")

        @self.bot.message_handler(content_types=['document'])
        def handle_session_upload(message):
            chat_id = message.chat.id
            document = message.document
            
            if not document.file_name.endswith('.json'):
                self.bot.reply_to(message, "❌ Please send a valid session JSON file.")
                return
            
            status_msg = self.bot.reply_to(message, "⏳ Processing session file...")
            
            try:
                # Download file from Telegram servers
                file_info = self.bot.get_file(document.file_id)
                downloaded_file = self.bot.download_file(file_info.file_path)
                
                # Check JSON validity
                import json
                session_data = json.loads(downloaded_file.decode('utf-8'))
                
                # Validate instagrapi structure
                if not isinstance(session_data, dict) or 'uuids' not in session_data:
                    self.bot.edit_message_text(
                        "❌ Invalid session JSON format. Please upload a valid instagrapi settings JSON file.",
                        chat_id=chat_id,
                        message_id=status_msg.message_id
                    )
                    return
                
                # Save session to correct SESSIONS_DIR path
                target_path = SESSIONS_DIR / f"instagram_session_{chat_id}.json"
                with open(target_path, "wb") as f:
                    f.write(downloaded_file)
                
                # Re-initialize/verify client
                client = get_client(chat_id)
                client.session_file = target_path
                success = client.try_load_session()
                
                if success:
                    self.bot.edit_message_text(
                        f"✅ **Instagram session loaded successfully!**\n"
                        f"Logged in as: `{client.current_username}`",
                        chat_id=chat_id,
                        message_id=status_msg.message_id,
                        parse_mode="Markdown"
                    )
                else:
                    self.bot.edit_message_text(
                        "❌ Failed to validate session. The session might be expired or invalid.",
                        chat_id=chat_id,
                        message_id=status_msg.message_id
                    )
            except Exception as e:
                logger.error(f"Session upload error: {e}")
                self.bot.edit_message_text(
                    f"❌ **Error processing file:** {str(e)}",
                    chat_id=chat_id,
                    message_id=status_msg.message_id
                )

        @self.bot.message_handler(func=lambda message: True)
        def handle_target_username(message):
            # Check if Instagram is logged in for this user
            client = get_client(message.chat.id)
            if not client.logged_in:
                self.bot.reply_to(
                    message, 
                    "❌ **Error:** You are not logged in. Please use `/login <username> <password>` first."
                )
                return

            parts = message.text.strip().split()
            target = parts[0]
            amount = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
            
            self.bot.reply_to(message, f"🔍 Fetching recent {amount} posts for **{target}**...")
            
            try:
                # Fetch recent posts/reels
                medias = client.get_profile_medias(target, amount=amount)
                if not medias:
                    self.bot.send_message(message.chat.id, "📭 No recent posts or reels found.")
                    return

                total = len(medias)
                progress_msg = self.bot.send_message(message.chat.id, f"⏳ **Sending Previews:** 0/{total}\n`[░░░░░░░░░░]`", parse_mode="Markdown")
                
                self.stop_flags[message.chat.id] = False

                for i, m in enumerate(medias):
                    if self.stop_flags.get(message.chat.id, False):
                        self.bot.send_message(message.chat.id, "🛑 Preview sending stopped.")
                        break

                    # Construct Inline Keyboard for reposting
                    markup = InlineKeyboardMarkup()
                    btn = InlineKeyboardButton("📤 Repost to Instagram", callback_data=f"repost_{m['id']}")
                    markup.add(btn)

                    caption = m['caption'][:150] + "..." if len(m['caption']) > 150 else m['caption']
                    info_text = (
                        f"📹 **Type:** {m['type'].upper()}\n"
                        f"💬 **Caption:** {caption or '_No caption_'}\n"
                        f"❤️ {m['like_count']} Likes | 💬 {m['comment_count']} Comments\n"
                        f"🔗 [Instagram Link]({m['url']})"
                    )

                    # Send thumbnail image preview
                    if m['thumbnail_url']:
                        try:
                            self.bot.send_photo(
                                message.chat.id, 
                                photo=m['thumbnail_url'], 
                                caption=info_text, 
                                reply_markup=markup, 
                                parse_mode="Markdown"
                            )
                        except Exception as e:
                            logger.error(f"Failed to send thumbnail image: {e}")
                            self.bot.send_message(
                                message.chat.id, 
                                f"{info_text}\n\n*(Preview unavailable)*", 
                                reply_markup=markup, 
                                parse_mode="Markdown"
                            )
                    else:
                        self.bot.send_message(
                            message.chat.id, 
                            info_text, 
                            reply_markup=markup, 
                            parse_mode="Markdown"
                        )
                    
                    # Update progress bar
                    perc = (i + 1) / total
                    bar_len = 10
                    filled = int(bar_len * perc)
                    bar = "█" * filled + "░" * (bar_len - filled)
                    try:
                        self.bot.edit_message_text(
                            f"⏳ **Sending Previews:** {i+1}/{total}\n`[{bar}]`", 
                            chat_id=message.chat.id, 
                            message_id=progress_msg.message_id,
                            parse_mode="Markdown"
                        )
                    except:
                        pass
                
                if not self.stop_flags.get(message.chat.id, False):
                    try:
                        self.bot.edit_message_text(
                            f"✅ **Sent all {total} previews!**", 
                            chat_id=message.chat.id, 
                            message_id=progress_msg.message_id,
                            parse_mode="Markdown"
                        )
                    except:
                        pass
                
                self.stop_flags[message.chat.id] = False

            except Exception as e:
                logger.error(f"Telegram Bot failed to process target: {e}")
                self.bot.send_message(message.chat.id, f"❌ **Error fetching profile:** {str(e)}")

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('repost_'))
        def handle_repost_callback(call):
            media_id = call.data.replace('repost_', '')
            chat_id = call.message.chat.id
            message_id = call.message.message_id
            
            # Check coins balance first
            user_data = get_user_data(chat_id)
            if user_data.get("coins", 0) <= 0:
                self.bot.answer_callback_query(call.id, "❌ Insufficient Coins! You have 0 coins left.", show_alert=True)
                return
            
            # Acknowledge callback click immediately
            self.bot.answer_callback_query(call.id, "Processing your repost request...")
            
            # Remove buttons to prevent multiple clicks
            try:
                self.bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except:
                pass
            
            status_msg = self.bot.send_message(chat_id, "⏳ **Initializing upload...**\n`[░░░░░░░░░░]` 0%", parse_mode="Markdown")
            
            stop_event = threading.Event()
            
            def update_progress():
                bar_len = 10
                for step in range(1, 10):
                    if stop_event.is_set():
                        break
                    filled = step
                    bar = "█" * filled + "░" * (bar_len - filled)
                    try:
                        self.bot.edit_message_text(
                            f"⏳ **Uploading to Instagram:** {step*10}%\n`[{bar}]`",
                            chat_id=chat_id,
                            message_id=status_msg.message_id,
                            parse_mode="Markdown"
                        )
                    except:
                        pass
                    # Wait 1.5s; break early if stop_event is set
                    if stop_event.wait(1.5):
                        break
            
            progress_thread = threading.Thread(target=update_progress)
            progress_thread.start()
            
            try:
                # Perform the repost workflow (inherits original caption)
                client = get_client(chat_id)
                result = client.repost_media(media_id)
                
                # Stop progress thread
                stop_event.set()
                progress_thread.join()
                
                # Deduct coin
                deduct_coin(chat_id)
                remaining_coins = get_user_data(chat_id).get("coins", 50)
                
                self.bot.delete_message(chat_id, status_msg.message_id)
                self.bot.send_message(
                    chat_id, 
                    f"✅ **Repost Successful!**\n"
                    f"• Type: `{result['type'].capitalize()}`\n"
                    f"• New Media ID: `{result['new_pk']}`\n"
                    f"🪙 **Coins remaining:** `{remaining_coins}`\n"
                    f"🗑️ _Video/Photo was instantly deleted from the server to save space._"
                )
            except Exception as e:
                stop_event.set()
                progress_thread.join()
                
                logger.error(f"Telegram Bot repost callback error: {e}")
                try:
                    self.bot.delete_message(chat_id, status_msg.message_id)
                except:
                    pass
                self.bot.send_message(chat_id, f"❌ **Repost failed:** {str(e)}")
                
                # Restore button if failed
                markup = InlineKeyboardMarkup()
                btn = InlineKeyboardButton("📤 Retry Repost", callback_data=f"repost_{media_id}")
                markup.add(btn)
                try:
                    self.bot.edit_message_reply_markup(chat_id, message_id, reply_markup=markup)
                except:
                    pass

def send_telegram_notification(text):
    """Utility to send notifications if enabled."""
    config = load_config()
    if not config.get("telegram_notifications_enabled", True):
        return

    token = config.get("telegram_token")
    chat_id = config.get("telegram_chat_id")
    
    if token and chat_id:
        try:
            bot = telebot.TeleBot(token)
            bot.send_message(chat_id, text, parse_mode="Markdown")
            logger.info("Telegram notification sent.")
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")

# Singleton Telegram Bot Manager
bot_manager = TelegramBotManager()
