"""
telethon_client.py - مدير حساب تيليجرام الشخصي (Telegram Client API)
Telethon Client Manager: Handles session lifecycle, auto-reconnect,
sending links to target bots, capturing inbound replies & media,
and clicking interactive inline buttons.
"""

import os
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PasswordHashInvalidError,
    PhoneNumberInvalidError,
    UserDeactivatedBanError,
    AuthKeyError
)
from telethon.tl.types import (
    ReplyInlineMarkup,
    MessageMediaPhoto,
    MessageMediaDocument
)

BRIDGE_DIR = Path(__file__).resolve().parent
MEDIA_DIR = BRIDGE_DIR / "data" / "media"
SESSIONS_DIR = BRIDGE_DIR / "data" / "sessions"

from config import (
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    TELEGRAM_PHONE,
    SESSION_STRING,
    DEFAULT_DESTINATION_BOT
)
from bridge_database import db
from bridge_models import MessageType, MessageDirection, InlineButtonInfo

logger = logging.getLogger(__name__)


class TelethonManager:
    """إدارة كاملة لحساب تيليجرام الشخصي كوسيط إرسال واستقبال"""

    def __init__(self):
        self.api_id: int = TELEGRAM_API_ID
        self.api_hash: str = TELEGRAM_API_HASH
        self.phone: str = TELEGRAM_PHONE
        self.session_str: str = SESSION_STRING

        self.client: Optional[TelegramClient] = None
        self._is_connected: bool = False
        self._reply_callback: Optional[Callable] = None

        # جلسات تسجيل الدخول المعلقة في الواجهة (Auth flow in progress)
        self._pending_auth: Dict[str, Any] = {}

    def set_reply_callback(self, cb: Callable):
        """تعيين دالة الاستدعاء عند وصول رد من البوت المستقبِل"""
        self._reply_callback = cb

    async def initialize(self) -> bool:
        """
        تهيئة العميل وبدء الاتصال بالحساب إذا كانت بيانات الجلسة متوفرة في القاعدة أو المتغيرات
        """
        # محاولة جلب الجلسة المحفوظة في قاعدة البيانات
        saved_acc = db.get_active_telegram_account()
        if not saved_acc:
            with db._get_connection() as conn:
                r = conn.cursor().execute("SELECT * FROM telegram_accounts ORDER BY id DESC LIMIT 1").fetchone()
                if r:
                    saved_acc = dict(r)

        if saved_acc and saved_acc.get("session_encrypted"):
            self.session_str = saved_acc["session_encrypted"]

        saved_api_id = db.get_setting("telegram_api_id")
        saved_api_hash = db.get_setting("telegram_api_hash")
        if saved_api_id and str(saved_api_id).isdigit():
            self.api_id = int(saved_api_id)
        if saved_api_hash:
            self.api_hash = saved_api_hash

        if not self.api_id or not self.api_hash or not self.session_str:
            logger.info("حساب تيليجرام الشخصي غير مهيأ بعد. يرجى ربط الحساب عبر لوحة التحكم.")
            return False

        try:
            session = StringSession(self.session_str)
            self.client = TelegramClient(session, self.api_id, self.api_hash)
            await self.client.connect()

            if not await self.client.is_user_authorized():
                logger.warning("جلسة تيليجرام الشخصية منتهية أو غير مصرح بها.")
                db.update_account_status(0, "EXPIRED")
                self._is_connected = False
                return False

            me = await self.client.get_me()
            self._is_connected = True
            masked_phone = f"{me.phone[:4]}****{me.phone[-3:]}" if me.phone and len(me.phone) > 7 else (me.phone or "")

            acc_data = {
                "user_id": me.id,
                "username": me.username or "",
                "first_name": me.first_name or "",
                "phone_masked": masked_phone,
                "is_active": True,
                "session_status": "CONNECTED",
                "session_encrypted": self.session_str,
                "last_connected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            db.save_telegram_account(acc_data)
            db.record_log("ACCOUNT_CONNECTED", f"تم ربط حساب تيليجرام الشخصي بنجاح: @{me.username} ({me.id})")
            logger.info(f"تم تسجيل الدخول بحساب تيليجرام الشخصي: @{me.username} ({me.id})")

            # تسجيل مستمع الرسائل الواردة من البوت المستقبِل
            self._register_event_handlers()
            return True

        except Exception as e:
            logger.error(f"خطأ أثناء الاتصال بحساب تيليجرام: {e}")
            self._is_connected = False
            return False

    def _register_event_handlers(self):
        """تسجيل مستمعات الأحداث للردود والرسائل الواردة من كافة بوتات الاستلام النشطة"""
        if not self.client:
            return

        @self.client.on(events.NewMessage)
        async def incoming_message_handler(event):
            sender = await event.get_sender()
            sender_username = (sender.username or "").lower() if sender and hasattr(sender, "username") else ""
            valid_targets = [u.lower() for u in db.get_active_destination_usernames()]

            # التأكد من أن الرسالة واردة من أحد بوتات الاستلام النشطة
            if sender_username and sender_username in valid_targets:
                await self._process_inbound_message(event.message, sender_username=sender.username)

        @self.client.on(events.MessageEdited)
        async def edited_message_handler(event):
            sender = await event.get_sender()
            sender_username = (sender.username or "").lower() if sender and hasattr(sender, "username") else ""
            valid_targets = [u.lower() for u in db.get_active_destination_usernames()]

            if sender_username and sender_username in valid_targets:
                await self._process_inbound_message(event.message, is_edit=True, sender_username=sender.username)

        logger.info("تم تفعيل مستمع الردود لبوتات الاستلام النشطة بنجاح.")

    async def _process_inbound_message(self, message, is_edit: bool = False, sender_username: Optional[str] = None):
        """معالجة رسالة الرد الواردة من البوت المستهدف واستخراج وسائطها وأزرارها"""
        try:
            text_content = message.message or ""
            msg_type = MessageType.TEXT
            media_path = None
            file_name = None

            # فحص وتنزيل الوسائط المرفقة (صور، ملفات، فيديو، صوت)
            if message.media:
                media_dir = MEDIA_DIR / datetime.now().strftime("%Y%m%d")
                media_dir.mkdir(parents=True, exist_ok=True)

                if isinstance(message.media, MessageMediaPhoto):
                    msg_type = MessageType.PHOTO
                    file_path = await message.download_media(file=str(media_dir))
                    media_path = str(file_path)
                elif isinstance(message.media, MessageMediaDocument):
                    msg_type = MessageType.DOCUMENT
                    file_path = await message.download_media(file=str(media_dir))
                    media_path = str(file_path)
                    file_name = getattr(message.file, "name", None) or Path(file_path).name

            # استخراج الأزرار التفاعلية (Inline Keyboard Buttons)
            buttons: List[List[InlineButtonInfo]] = []
            has_buttons = False
            if message.reply_markup and isinstance(message.reply_markup, ReplyInlineMarkup):
                has_buttons = True
                for row_idx, row in enumerate(message.reply_markup.rows):
                    btn_row = []
                    for col_idx, btn in enumerate(row.buttons):
                        lbl = btn.text
                        data_val = getattr(btn, "data", b"").decode("utf-8", errors="ignore") if hasattr(btn, "data") else None
                        url_val = getattr(btn, "url", None)
                        btn_row.append(InlineButtonInfo(
                            label=lbl,
                            data=data_val,
                            url=url_val,
                            row=row_idx,
                            col=col_idx
                        ))
                    if btn_row:
                        buttons.append(btn_row)

            reply_payload = {
                "direction": MessageDirection.INBOUND.value,
                "message_type": msg_type.value,
                "text_content": text_content,
                "media_path": media_path,
                "file_name": file_name,
                "telegram_message_id": message.id,
                "has_buttons": has_buttons,
                "buttons": [b.dict() for row in buttons for b in row] if buttons else None,
                "raw_buttons": buttons,
                "is_edit": is_edit,
                "sender_username": sender_username,
                "received_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            # إشعار Queue Manager بالرد الوارد
            if self._reply_callback:
                await self._reply_callback(reply_payload)

        except Exception as e:
            logger.error(f"خطأ أثناء معالجة رد البوت المستهدف: {e}")

    async def send_to_target(self, target_bot: str, text_or_link: str) -> int:
        """
        إرسال الرابط أو الرسالة إلى البوت المستهدف باستخدام حساب تيليجرام الشخصي
        ويرجع معرف الرسالة المرسلة telegram_message_id
        """
        if not self._is_connected or not self.client:
            raise ConnectionError("حساب تيليجرام الشخصي غير متصل حالياً.")

        clean_target = target_bot.replace("@", "").strip()
        sent_msg = await self.client.send_message(clean_target, text_or_link)
        logger.info(f"تم إرسال الرابط بنجاح إلى @{clean_target} (Message ID: {sent_msg.id})")
        return sent_msg.id

    async def click_button(self, target_bot: str, message_id: int, row: int, col: int, data: Optional[str] = None) -> bool:
        """
        الضغط الفعلي على زر تفاعلي في رسالة البوت المستقبِل باستخدام الحساب الشخصي
        """
        if not self._is_connected or not self.client:
            raise ConnectionError("حساب تيليجرام الشخصي غير متصل.")

        clean_target = target_bot.replace("@", "").strip()
        msg = await self.client.get_messages(clean_target, ids=message_id)
        if not msg:
            # البحث في أحدث الرسائل الصادرة من البوت المستهدف
            recent = await self.client.get_messages(clean_target, limit=10)
            for m in recent:
                if m and (m.id == message_id or (m.reply_markup and hasattr(m.reply_markup, "rows"))):
                    msg = m
                    break

        if not msg:
            logger.warning(f"لم يتم العثور على رسالة الزر #{message_id} لدى @{clean_target}")
            return False

        try:
            if data:
                await msg.click(data=data.encode())
            else:
                await msg.click(row=row, col=col)
            logger.info(f"تم الضغط على الزر بنجاح في الرسالة #{msg.id} (row={row}, col={col})")
            return True
        except Exception as e:
            logger.error(f"خطأ أثناء الضغط على الزر: {e}")
            return False
            return False

    async def test_connection(self) -> Dict[str, Any]:
        """اختبار الاتصال الفعلي بالحساب الشخصي وبالبوت المستقبِل"""
        if not self.client or not self._is_connected:
            return {"success": False, "error": "الحساب غير متصل حالياً."}

        try:
            me = await self.client.get_me()
            target_bot = db.get_setting("default_destination", DEFAULT_DESTINATION_BOT).replace("@", "")
            target_entity = await self.client.get_entity(target_bot)

            return {
                "success": True,
                "user_id": me.id,
                "username": me.username or me.first_name,
                "target_bot": target_bot,
                "target_bot_id": target_entity.id,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    #  واجهة ربط الحساب الآمنة (Auth Flow Wizard)
    # =========================================================================

    async def start_auth_wizard(self, api_id: int, api_hash: str, phone: str) -> Dict[str, Any]:
        """
        بدء عملية تسجيل الدخول الآمنة عبر كود التحقق
        """
        try:
            temp_session = StringSession()
            temp_client = TelegramClient(temp_session, api_id, api_hash)
            await temp_client.connect()

            sent_code = await temp_client.send_code_request(phone)

            # تخزين البيانات المؤقتة في الذاكرة بأمان
            self._pending_auth = {
                "client": temp_client,
                "session": temp_session,
                "api_id": api_id,
                "api_hash": api_hash,
                "phone": phone,
                "phone_code_hash": sent_code.phone_code_hash,
                "started_at": datetime.now()
            }

            return {
                "success": True,
                "message": f"تم إرسال كود التحقق إلى حسابك في تيليجرام على الرقم {phone}",
                "phone_code_hash": sent_code.phone_code_hash
            }
        except PhoneNumberInvalidError:
            return {"success": False, "error": "رقم الهاتف غير صالح، تأكد من كتابة كود الدولة (+20...)"}
        except Exception as e:
            return {"success": False, "error": f"خطأ أثناء طلب كود التحقق: {e}"}

    async def complete_auth_with_code(self, code: str, password: Optional[str] = None) -> Dict[str, Any]:
        """
        إكمال تسجيل الدخول بواسطة كود التحقق (وكلمة المرور للتحقق بخطوتين إن وُجدت)
        """
        if not self._pending_auth or "client" not in self._pending_auth:
            return {"success": False, "error": "لا توجد عملية تسجيل دخول جارية حالياً."}

        client: TelegramClient = self._pending_auth["client"]
        phone: str = self._pending_auth["phone"]
        code_hash: str = self._pending_auth["phone_code_hash"]

        try:
            try:
                await client.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
            except SessionPasswordNeededError:
                if not password:
                    return {
                        "success": False,
                        "requires_2fa": True,
                        "message": "الحساب محمي بالتحقق بخطوتين (Two-Step Verification). يرجى إدخال كلمة المرور."
                    }
                await client.sign_in(password=password)

            me = await client.get_me()
            session_str = client.session.save()

            # حفظ الإعدادات في قاعدة البيانات
            db.set_setting("telegram_api_id", str(self._pending_auth["api_id"]))
            db.set_setting("telegram_api_hash", str(self._pending_auth["api_hash"]))

            masked_phone = f"{me.phone[:4]}****{me.phone[-3:]}" if me.phone and len(me.phone) > 7 else (me.phone or "")
            acc_data = {
                "user_id": me.id,
                "username": me.username or "",
                "first_name": me.first_name or "",
                "phone_masked": masked_phone,
                "is_active": True,
                "session_status": "CONNECTED",
                "session_encrypted": session_str,
                "last_connected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            db.save_telegram_account(acc_data)

            # ترقية العميل ليصبح العميل الرسمي للنظام
            self.client = client
            self.session_str = session_str
            self.api_id = self._pending_auth["api_id"]
            self.api_hash = self._pending_auth["api_hash"]
            self.phone = phone
            self._is_connected = True

            self._register_event_handlers()
            self._pending_auth = {}

            db.record_log("ACCOUNT_CONNECTED", f"تم ربط حساب جديد بنجاح: @{me.username} ({me.id})")
            return {
                "success": True,
                "user_id": me.id,
                "username": me.username or me.first_name,
                "message": "تم ربط وتفعيل حسابك الشخصي بنجاح!"
            }

        except PhoneCodeInvalidError:
            return {"success": False, "error": "كود التحقق غير صحيح، يرجى المحاولة مرة أخرى."}
        except PasswordHashInvalidError:
            return {"success": False, "error": "كلمة مرور التحقق بخطوتين (2FA) غير صحيحة."}
        except Exception as e:
            return {"success": False, "error": f"فشل تسجيل الدخول: {e}"}

    async def check_bot_entity(self, bot_username: str) -> Dict[str, Any]:
        """فحص ما إذا كان البوت موجوداً وإمكانية الوصول إليه عبر حساب تيليجرام الشخصي"""
        if not self.client or not self._is_connected:
            return {"success": False, "error": "حساب تيليجرام الشخصي غير متصل حالياً."}
        clean = bot_username.replace("@", "").strip()
        try:
            entity = await self.client.get_entity(clean)
            title = getattr(entity, "first_name", clean) or clean
            if getattr(entity, "last_name", None):
                title = f"{title} {entity.last_name}"
            return {
                "success": True,
                "id": entity.id,
                "username": getattr(entity, "username", clean),
                "title": title,
                "is_bot": getattr(entity, "bot", True)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def disconnect(self):
        """فصل الجلسة الحالية"""
        if self.client and self._is_connected:
            await self.client.disconnect()
        self._is_connected = False
        db.disconnect_telegram_account()
        db.record_log("ACCOUNT_DISCONNECTED", "تم فصل حساب تيليجرام الشخصي يدوياً.")


# كائن مدير تيليجرام العام
telethon_manager = TelethonManager()
