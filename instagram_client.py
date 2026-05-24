import os
import shutil
import logging
import tempfile
from pathlib import Path
from instagrapi import Client
from instagrapi.exceptions import TwoFactorRequired, ChallengeRequired, LoginRequired
from user_manager import set_user_instagram, get_user_instagram

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Use DATA_DIR from environment for persistent storage (e.g. Render), else default to current dir
DATA_DIR = Path(os.getenv("DATA_DIR", "."))
SESSIONS_DIR = DATA_DIR / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)
TEMP_DIR = Path(tempfile.gettempdir()) / "veo_temp_media"

class InstagramClientManager:
    def __init__(self, chat_id):
        self.chat_id = str(chat_id)
        self.session_file = SESSIONS_DIR / f"instagram_session_{self.chat_id}.json"
        self.cl = Client(request_timeout=60)
        self.cl.delay_range = [2, 5]  # Introduce slight delays to avoid rate limits
        self.logged_in = False
        self.current_username = None
        self.try_load_session()

    def try_load_session(self):
        """Attempts to load a saved session from disk to avoid password login."""
        if self.session_file.exists():
            try:
                logger.info(f"[{self.chat_id}] Attempting to load saved Instagram session...")
                self.cl.load_settings(self.session_file)
                # Verify session is still valid by getting timeline feed
                self.cl.get_timeline_feed()
                self.logged_in = True
                self.current_username = get_user_instagram(self.chat_id) or self.cl.username
                logger.info(f"[{self.chat_id}] Instagram session successfully loaded for: {self.current_username}")
                return True
            except Exception as e:
                logger.warning(f"[{self.chat_id}] Saved session is invalid or expired: {e}")
                # Reset client and clean up invalid session file
                try:
                    self.session_file.unlink()
                except:
                    pass
                self.cl = Client(request_timeout=60)
                self.cl.delay_range = [2, 5]
                self.logged_in = False
                self.current_username = None
        return False

    def login(self, username, password, verification_code=None):
        """Log in to Instagram and save session if successful."""
        try:
            logger.info(f"[{self.chat_id}] Attempting login for user: {username}")
            if verification_code:
                # Log in with 2FA verification code
                self.cl.login(username, password, verification_code=verification_code)
            else:
                self.cl.login(username, password)
            
            # If we get here, login was successful
            self.cl.dump_settings(self.session_file)
            self.logged_in = True
            self.current_username = username
            set_user_instagram(self.chat_id, username)
            logger.info(f"[{self.chat_id}] Successfully logged in and saved session for: {username}")
            return {"status": "success", "username": username}

        except TwoFactorRequired as e:
            logger.info(f"[{self.chat_id}] Two-factor authentication required for login.")
            return {
                "status": "two_factor_required",
                "message": "Two-factor verification code is required to complete login."
            }
        except ChallengeRequired as e:
            logger.warning(f"[{self.chat_id}] Instagram login challenge required.")
            return {
                "status": "challenge_required",
                "message": "Security challenge required. Please resolve this challenge on a physical device, then try again."
            }
        except Exception as e:
            logger.error(f"[{self.chat_id}] Login failed: {e}")
            return {"status": "error", "message": str(e)}

    def logout(self):
        """Logs out from Instagram and deletes saved session files."""
        try:
            self.cl.logout()
        except:
            pass
        
        if self.session_file.exists():
            try:
                self.session_file.unlink()
            except:
                pass
        
        self.cl = Client(request_timeout=60)
        self.cl.delay_range = [2, 5]
        self.logged_in = False
        self.current_username = None
        logger.info(f"[{self.chat_id}] Logged out and session cleared.")
        return {"status": "success"}

    def get_profile_medias(self, target_username, amount=12):
        """Fetches posts/reels of a target username."""
        if not self.logged_in:
            raise LoginRequired("You must be logged in to fetch posts.")

        try:
            logger.info(f"Fetching {amount} posts for target: {target_username}")
            # Clean handle name (remove URL or @ if present)
            target = target_username.strip()
            if "/" in target:
                # It's a URL, extract the username
                parts = target.rstrip("/").split("/")
                target = parts[-1].split("?")[0]
            target = target.lstrip("@")

            user_id = self.cl.user_id_from_username(target)
            medias = self.cl.user_medias(user_id, amount=amount)
            
            result = []
            for m in medias:
                # Determine type
                media_type_str = "photo"
                if m.media_type == 1:
                    media_type_str = "photo"
                elif m.media_type == 2:
                    if m.product_type == "clips":
                        media_type_str = "reel"
                    else:
                        media_type_str = "video"
                elif m.media_type == 8:
                    media_type_str = "album"

                # Check thumbnail URL
                thumbnail = str(m.thumbnail_url) if m.thumbnail_url else None
                
                result.append({
                    "id": m.id,
                    "code": m.code,
                    "type": media_type_str,
                    "caption": m.caption_text or "",
                    "thumbnail_url": thumbnail,
                    "video_url": str(m.video_url) if m.video_url else None,
                    "like_count": m.like_count,
                    "comment_count": m.comment_count,
                    "taken_at": m.taken_at.isoformat() if m.taken_at else None,
                    "url": f"https://www.instagram.com/p/{m.code}/"
                })
            return result
        except Exception as e:
            logger.error(f"Error fetching profile medias for {target_username}: {e}")
            raise e

    def repost_media(self, media_pk, target_caption=None):
        """Downloads a post and uploads it as your own with the given or original caption."""
        if not self.logged_in:
            raise LoginRequired("You must be logged in to repost.")

        # Create unique folder for this task to avoid concurrency issues
        task_dir = TEMP_DIR / f"repost_{media_pk}"
        task_dir.mkdir(parents=True, exist_ok=True)

        try:
            logger.info(f"Starting repost workflow for media PK: {media_pk}")
            # Fetch media info
            media_info = self.cl.media_info(media_pk)
            caption = target_caption if target_caption is not None else (media_info.caption_text or "")

            # Post type logic
            if media_info.media_type == 1:
                # 1. Photo
                logger.info("Downloading photo...")
                path = self.cl.photo_download(media_pk, folder=task_dir)
                logger.info(f"Downloaded to {path}. Uploading photo...")
                uploaded = self.cl.photo_upload(path, caption)
                logger.info(f"Photo uploaded. PK: {uploaded.pk}")
                return {"status": "success", "new_pk": uploaded.pk, "type": "photo"}

            elif media_info.media_type == 2:
                # 2. Video or Reel
                logger.info("Downloading cover thumbnail...")
                thumbnail_path = None
                if media_info.thumbnail_url:
                    try:
                        thumbnail_path = self.cl.photo_download_by_url(media_info.thumbnail_url, folder=task_dir)
                        logger.info(f"Downloaded thumbnail to {thumbnail_path}")
                    except Exception as e:
                        logger.warning(f"Failed to download original thumbnail: {e}")

                if media_info.product_type == "clips":
                    logger.info("Downloading Reel (clip)...")
                    path = self.cl.clip_download(media_pk, folder=task_dir)
                    logger.info(f"Downloaded to {path}. Uploading Reel (clip)...")
                    uploaded = self.cl.clip_upload(path, caption, thumbnail=thumbnail_path)
                    logger.info(f"Reel uploaded. PK: {uploaded.pk}")
                    return {"status": "success", "new_pk": uploaded.pk, "type": "reel"}
                else:
                    logger.info("Downloading video...")
                    path = self.cl.video_download(media_pk, folder=task_dir)
                    logger.info(f"Downloaded to {path}. Uploading video...")
                    uploaded = self.cl.video_upload(path, caption, thumbnail=thumbnail_path)
                    logger.info(f"Video uploaded. PK: {uploaded.pk}")
                    return {"status": "success", "new_pk": uploaded.pk, "type": "video"}

            elif media_info.media_type == 8:
                # 3. Album
                logger.info("Downloading album resources...")
                paths = self.cl.album_download(media_pk, folder=task_dir)
                logger.info(f"Downloaded {len(paths)} resources. Uploading album...")
                uploaded = self.cl.album_upload(paths, caption)
                logger.info(f"Album uploaded. PK: {uploaded.pk}")
                return {"status": "success", "new_pk": uploaded.pk, "type": "album"}
            
            else:
                raise ValueError(f"Unsupported media type: {media_info.media_type}")

        except Exception as e:
            logger.error(f"Error during reposting: {e}")
            raise e
        finally:
            # Clean up temporary downloads
            if task_dir.exists():
                logger.info(f"Cleaning up temporary files in {task_dir}")
                shutil.rmtree(task_dir)

# Manage multiple clients
_clients = {}

def get_client(chat_id):
    chat_id = str(chat_id)
    if chat_id not in _clients:
        _clients[chat_id] = InstagramClientManager(chat_id)
    return _clients[chat_id]
