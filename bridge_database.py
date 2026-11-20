"""
database.py - قاعدة البيانات الدائمة لنظام VIP STORE LINK BRIDGE
Dual Engine: Local SQLite (ACID, persistent) + Supabase Cloud Sync
"""

import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

BRIDGE_DIR = Path(__file__).resolve().parent
DB_PATH = BRIDGE_DIR / "data" / "vip_store_bridge.db"

from config import SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)

# عميل Supabase
_supabase_client = None

def get_supabase_client():
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            from supabase import create_client
            _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
            logger.info("تم الاتصال بـ Supabase بنجاح (LINK BRIDGE).")
            return _supabase_client
        except Exception as e:
            logger.warning(f"تعذر الاتصال بـ Supabase: {e}")
            return None
    return None


class BridgeDatabase:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """إنشاء الجداول المحلية المطابقة تماماً لمخطط Supabase"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. إعدادات النظام
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS bridge_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                description TEXT,
                updated_at TEXT
            );
            """)

            # 2. حسابات تيليجرام الشخصية
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS telegram_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                username TEXT,
                first_name TEXT,
                phone_masked TEXT,
                is_active INTEGER DEFAULT 1,
                session_status TEXT DEFAULT 'DISCONNECTED',
                session_encrypted TEXT,
                last_connected_at TEXT,
                last_seen_at TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """)

            # 3. الوجهات
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS bridge_destinations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_username TEXT UNIQUE NOT NULL,
                bot_title TEXT,
                description TEXT,
                is_default INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT
            );
            """)

            # 4. العمليات
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS bridge_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                original_link TEXT NOT NULL,
                raw_message_text TEXT,
                destination_bot TEXT NOT NULL,
                sent_out_message_id INTEGER,
                status TEXT NOT NULL DEFAULT 'PENDING',
                replies_count INTEGER DEFAULT 0,
                has_buttons INTEGER DEFAULT 0,
                error_message TEXT,
                sent_at TEXT,
                last_reply_at TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """)

            # 5. الرسائل والوسائط
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS bridge_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id TEXT NOT NULL,
                direction TEXT NOT NULL,
                message_type TEXT NOT NULL,
                text_content TEXT,
                media_path TEXT,
                file_id TEXT,
                file_name TEXT,
                mime_type TEXT,
                telegram_message_id INTEGER,
                reply_to_message_id INTEGER,
                has_buttons INTEGER DEFAULT 0,
                buttons_json TEXT,
                created_at TEXT,
                FOREIGN KEY(transaction_id) REFERENCES bridge_transactions(transaction_id)
            );
            """)

            # 6. تفاعل الأزرار
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS bridge_callbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id TEXT NOT NULL,
                button_label TEXT NOT NULL,
                button_data TEXT,
                button_row INTEGER,
                button_col INTEGER,
                clicked_by_user_id INTEGER NOT NULL,
                click_status TEXT DEFAULT 'PENDING',
                result_text TEXT,
                clicked_at TEXT,
                FOREIGN KEY(transaction_id) REFERENCES bridge_transactions(transaction_id)
            );
            """)

            # 7. سجلات التدقيق
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS bridge_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id TEXT,
                event_type TEXT NOT NULL,
                level TEXT DEFAULT 'INFO',
                message TEXT NOT NULL,
                metadata_json TEXT,
                created_at TEXT
            );
            """)

            # 8. المشرفين
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS bridge_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                role TEXT DEFAULT 'ADMIN',
                is_active INTEGER DEFAULT 1,
                created_at TEXT
            );
            """)

            # القيم الافتراضية
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
            INSERT OR IGNORE INTO bridge_settings (key, value, description, updated_at) VALUES 
            ('forwarding_enabled', 'true', 'حالة تفعيل تحويل الروابط تلقائياً', ?),
            ('default_destination', 'MidasbuyHelp_bot', 'البوت المستقبِل الافتراضي', ?),
            ('reply_timeout_seconds', '60', 'مهلة انتظار رد البوت المستقبِل بالثواني', ?),
            ('queue_settle_seconds', '3.0', 'مدة انتظار استقرار وتتالي الرسائل بالثواني', ?),
            ('send_full_text_with_link', 'false', 'إرسال النص المصاحب للرابط أم الرابط فقط', ?);
            """, (now_str, now_str, now_str, now_str, now_str))

            cursor.execute("""
            INSERT OR IGNORE INTO bridge_destinations (bot_username, bot_title, is_default, is_active, created_at, updated_at)
            VALUES ('MidasbuyHelp_bot', 'Midasbuy Help Bot', 1, 1, ?, ?);
            """, (now_str, now_str))

            conn.commit()
            logger.info("تمت تهيئة قاعدة بيانات VIP STORE LINK BRIDGE بنجاح.")

    # --- إدارة الإعدادات ---

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM bridge_settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO bridge_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;
            """, (key, str(value), now_str))
            conn.commit()

        sb = get_supabase_client()
        if sb:
            try:
                sb.table("bridge_settings").upsert({"key": key, "value": str(value), "updated_at": now_str}).execute()
            except Exception as e:
                logger.warning(f"Supabase set_setting error: {e}")

    def get_all_settings(self) -> Dict[str, str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM bridge_settings")
            return {row["key"]: row["value"] for row in cursor.fetchall()}

    # --- إدارة حسابات تيليجرام الشخصية ---

    def save_telegram_account(self, account_data: Dict[str, Any]):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO telegram_accounts (
                user_id, username, first_name, phone_masked, is_active,
                session_status, session_encrypted, last_connected_at, last_seen_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                phone_masked = excluded.phone_masked,
                is_active = excluded.is_active,
                session_status = excluded.session_status,
                session_encrypted = CASE WHEN excluded.session_encrypted != '' THEN excluded.session_encrypted ELSE telegram_accounts.session_encrypted END,
                last_connected_at = excluded.last_connected_at,
                last_seen_at = excluded.last_seen_at,
                updated_at = excluded.updated_at;
            """, (
                account_data.get("user_id"),
                account_data.get("username", ""),
                account_data.get("first_name", ""),
                account_data.get("phone_masked", ""),
                1 if account_data.get("is_active", True) else 0,
                account_data.get("session_status", "CONNECTED"),
                account_data.get("session_encrypted", ""),
                account_data.get("last_connected_at", now_str),
                now_str,
                now_str,
                now_str
            ))
            conn.commit()

        sb = get_supabase_client()
        if sb:
            try:
                sb.table("telegram_accounts").upsert({
                    "user_id": account_data.get("user_id"),
                    "username": account_data.get("username"),
                    "first_name": account_data.get("first_name"),
                    "phone_masked": account_data.get("phone_masked"),
                    "is_active": account_data.get("is_active", True),
                    "session_status": account_data.get("session_status", "CONNECTED"),
                    "last_connected_at": account_data.get("last_connected_at", now_str),
                    "last_seen_at": now_str,
                    "updated_at": now_str
                }).execute()
            except Exception as e:
                logger.warning(f"Supabase save_account error: {e}")

    def get_active_telegram_account(self) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM telegram_accounts WHERE is_active = 1 ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_account_status(self, user_id: int, status: str):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE telegram_accounts SET session_status = ?, last_seen_at = ?, updated_at = ?
            WHERE user_id = ?
            """, (status, now_str, now_str, user_id))
            conn.commit()

    def disconnect_telegram_account(self, user_id: Optional[int] = None):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if user_id:
                cursor.execute("""
                UPDATE telegram_accounts SET is_active = 0, session_status = 'DISCONNECTED', updated_at = ?
                WHERE user_id = ?
                """, (now_str, user_id))
            else:
                cursor.execute("""
                UPDATE telegram_accounts SET is_active = 0, session_status = 'DISCONNECTED', updated_at = ?
                """, (now_str,))
            conn.commit()

    # --- إدارة العمليات (Transactions) ---

    def create_transaction(self, data: Dict[str, Any]) -> str:
        txn_id = data["transaction_id"]
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO bridge_transactions (
                transaction_id, user_id, chat_id, original_link, raw_message_text,
                destination_bot, status, replies_count, has_buttons, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                txn_id,
                data["user_id"],
                data["chat_id"],
                data["original_link"],
                data.get("raw_message_text", ""),
                data.get("destination_bot", "MidasbuyHelp_bot"),
                data.get("status", "PENDING"),
                0,
                0,
                now_str,
                now_str
            ))
            conn.commit()

        sb = get_supabase_client()
        if sb:
            try:
                sb.table("bridge_transactions").insert({
                    "transaction_id": txn_id,
                    "user_id": data["user_id"],
                    "chat_id": data["chat_id"],
                    "original_link": data["original_link"],
                    "raw_message_text": data.get("raw_message_text", ""),
                    "destination_bot": data.get("destination_bot", "MidasbuyHelp_bot"),
                    "status": data.get("status", "PENDING"),
                    "created_at": now_str,
                    "updated_at": now_str
                }).execute()
            except Exception as e:
                logger.warning(f"Supabase create_transaction error: {e}")

        return txn_id

    def update_transaction(self, txn_id: str, updates: Dict[str, Any]):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        updates["updated_at"] = now_str

        fields = []
        values = []
        for k, v in updates.items():
            fields.append(f"{k} = ?")
            values.append(v)
        values.append(txn_id)

        query = f"UPDATE bridge_transactions SET {', '.join(fields)} WHERE transaction_id = ?"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(values))
            conn.commit()

        sb = get_supabase_client()
        if sb:
            try:
                sb.table("bridge_transactions").update(updates).eq("transaction_id", txn_id).execute()
            except Exception as e:
                logger.warning(f"Supabase update_transaction error: {e}")

    def get_transaction(self, txn_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bridge_transactions WHERE transaction_id = ?", (txn_id,))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                d["messages"] = self.get_transaction_messages(txn_id)
                return d
            return None

    def get_active_transaction(self) -> Optional[Dict[str, Any]]:
        """جلب العملية النشطة حالياً التي تنتظر الرد أو قيد المعالجة"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT * FROM bridge_transactions 
            WHERE status IN ('SENDING', 'SENT', 'WAITING_FOR_REPLY', 'PROCESSING')
            ORDER BY id ASC LIMIT 1
            """)
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_transactions(self, limit: int = 50, status: Optional[str] = None, search: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM bridge_transactions WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if search:
            query += " AND (transaction_id LIKE ? OR original_link LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            return [dict(r) for r in cursor.fetchall()]

    # --- إدارة الرسائل والوسائط ---

    def save_message(self, data: Dict[str, Any]) -> int:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        buttons = data.get("buttons")
        buttons_json = json.dumps(buttons, ensure_ascii=False) if buttons else None

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO bridge_messages (
                transaction_id, direction, message_type, text_content, media_path,
                file_id, file_name, mime_type, telegram_message_id, reply_to_message_id,
                has_buttons, buttons_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["transaction_id"],
                data["direction"],
                data["message_type"],
                data.get("text_content"),
                data.get("media_path"),
                data.get("file_id"),
                data.get("file_name"),
                data.get("mime_type"),
                data.get("telegram_message_id"),
                data.get("reply_to_message_id"),
                1 if data.get("has_buttons") else 0,
                buttons_json,
                now_str
            ))
            msg_id = cursor.lastrowid

            # زيادة عدد الردود إذا كانت واردة INBOUND
            if data["direction"] == "INBOUND":
                cursor.execute("""
                UPDATE bridge_transactions 
                SET replies_count = replies_count + 1, last_reply_at = ?, has_buttons = CASE WHEN ? THEN 1 ELSE has_buttons END
                WHERE transaction_id = ?
                """, (now_str, 1 if data.get("has_buttons") else 0, data["transaction_id"]))

            conn.commit()

        sb = get_supabase_client()
        if sb:
            try:
                sb.table("bridge_messages").insert({
                    "transaction_id": data["transaction_id"],
                    "direction": data["direction"],
                    "message_type": data["message_type"],
                    "text_content": data.get("text_content"),
                    "media_path": data.get("media_path"),
                    "file_name": data.get("file_name"),
                    "telegram_message_id": data.get("telegram_message_id"),
                    "has_buttons": bool(data.get("has_buttons")),
                    "buttons_json": buttons_json,
                    "created_at": now_str
                }).execute()
            except Exception as e:
                logger.warning(f"Supabase save_message error: {e}")

        return msg_id

    def get_transaction_messages(self, txn_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bridge_messages WHERE transaction_id = ? ORDER BY id ASC", (txn_id,))
            messages = []
            for r in cursor.fetchall():
                d = dict(r)
                if d.get("buttons_json"):
                    try:
                        d["buttons"] = json.loads(d["buttons_json"])
                    except Exception:
                        d["buttons"] = None
                messages.append(d)
            return messages

    # --- إدارة تفاعل الأزرار ---

    def record_callback(self, data: Dict[str, Any]):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO bridge_callbacks (
                transaction_id, button_label, button_data, button_row, button_col,
                clicked_by_user_id, click_status, result_text, clicked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["transaction_id"],
                data["button_label"],
                data.get("button_data", ""),
                data.get("button_row", 0),
                data.get("button_col", 0),
                data["clicked_by_user_id"],
                data.get("click_status", "SENT_TO_TARGET"),
                data.get("result_text", ""),
                now_str
            ))
            conn.commit()

    # --- تسجيل الأحداث والتدقيق (Logs) ---

    def record_log(self, event_type: str, message: str, txn_id: Optional[str] = None, level: str = "INFO", metadata: Optional[Dict] = None):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO bridge_logs (transaction_id, event_type, level, message, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (txn_id, event_type, level, message, meta_json, now_str))
            conn.commit()

    def get_recent_logs(self, limit: int = 40) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bridge_logs ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    # --- إحصائيات النظام ---

    def get_stats(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS total FROM bridge_transactions")
            total = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) AS completed FROM bridge_transactions WHERE status = 'COMPLETED'")
            completed = cursor.fetchone()["completed"]

            cursor.execute("SELECT COUNT(*) AS failed FROM bridge_transactions WHERE status IN ('FAILED', 'TIMEOUT')")
            failed = cursor.fetchone()["failed"]

            cursor.execute("SELECT COUNT(*) AS pending FROM bridge_transactions WHERE status IN ('PENDING', 'SENDING', 'SENT', 'WAITING_FOR_REPLY', 'PROCESSING')")
            pending = cursor.fetchone()["pending"]

            cursor.execute("SELECT COUNT(*) AS total_replies FROM bridge_messages WHERE direction = 'INBOUND'")
            replies = cursor.fetchone()["total_replies"]

            return {
                "total_transactions": total,
                "completed": completed,
                "failed": failed,
                "pending": pending,
                "total_replies": replies,
                "success_rate": (completed / total * 100.0) if total > 0 else 0.0
            }

    # --- إدارة الوجهات وبوتات الاستلام (Destinations / Receiving Bots) ---

    def get_destinations(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bridge_destinations WHERE is_active = 1 ORDER BY is_default DESC, id ASC")
            return [dict(r) for r in cursor.fetchall()]

    def get_active_destination_usernames(self) -> List[str]:
        dest_list = self.get_destinations()
        usernames = {d["bot_username"].lower() for d in dest_list}
        def_dest = self.get_setting("default_destination", "MidasbuyHelp_bot").replace("@", "").lower()
        if def_dest:
            usernames.add(def_dest)
        return list(usernames)

    def add_destination(self, bot_username: str, bot_title: Optional[str] = None, is_default: bool = False) -> bool:
        clean_user = bot_username.replace("@", "").strip()
        title = bot_title or clean_user
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM bridge_destinations WHERE is_active = 1")
            count = cursor.fetchone()[0]
            make_default = 1 if (is_default or count == 0) else 0

            if make_default:
                cursor.execute("UPDATE bridge_destinations SET is_default = 0")

            cursor.execute("""
            INSERT INTO bridge_destinations (bot_username, bot_title, is_default, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(bot_username) DO UPDATE SET
                bot_title = COALESCE(?, bot_title),
                is_active = 1,
                is_default = CASE WHEN ? = 1 THEN 1 ELSE bridge_destinations.is_default END,
                updated_at = ?;
            """, (clean_user, title, make_default, now_str, now_str, title, make_default, now_str))
            conn.commit()

        if make_default:
            self.set_setting("default_destination", clean_user)
        return True

    def set_default_destination(self, bot_username: str) -> bool:
        clean_user = bot_username.replace("@", "").strip()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE bridge_destinations SET is_default = 0")
            cursor.execute("""
            INSERT INTO bridge_destinations (bot_username, bot_title, is_default, is_active, created_at, updated_at)
            VALUES (?, ?, 1, 1, ?, ?)
            ON CONFLICT(bot_username) DO UPDATE SET is_default = 1, is_active = 1, updated_at = ?;
            """, (clean_user, clean_user, now_str, now_str, now_str))
            conn.commit()
        self.set_setting("default_destination", clean_user)
        return True

    def remove_destination(self, bot_username: str) -> bool:
        clean_user = bot_username.replace("@", "").strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE bridge_destinations SET is_active = 0, is_default = 0 WHERE LOWER(bot_username) = LOWER(?)", (clean_user,))
            cursor.execute("SELECT bot_username FROM bridge_destinations WHERE is_active = 1 AND is_default = 1")
            has_default = cursor.fetchone()
            if not has_default:
                cursor.execute("SELECT bot_username FROM bridge_destinations WHERE is_active = 1 LIMIT 1")
                first = cursor.fetchone()
                if first:
                    cursor.execute("UPDATE bridge_destinations SET is_default = 1 WHERE bot_username = ?", (first[0],))
                    self.set_setting("default_destination", first[0])
            conn.commit()
        return True

    def get_destination(self, bot_username: str) -> Optional[Dict[str, Any]]:
        clean_user = bot_username.replace("@", "").strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bridge_destinations WHERE LOWER(bot_username) = LOWER(?) AND is_active = 1", (clean_user,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    # --- إدارة المستخدمين والأدمنز المصرح لهم (Authorized / Whitelist Users & Admins) ---

    def add_allowed_user(self, user_id: int, username: Optional[str] = None, full_name: Optional[str] = None, role: str = "ADMIN") -> bool:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO bridge_users (user_id, username, full_name, role, is_active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET 
                is_active = 1, 
                username = COALESCE(?, username), 
                full_name = COALESCE(?, full_name), 
                role = ?;
            """, (user_id, username, full_name, role, now_str, username, full_name, role))
            conn.commit()
        return True

    def remove_allowed_user(self, user_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE bridge_users SET is_active = 0 WHERE user_id = ?", (user_id,))
            conn.commit()
        return True

    def update_user_role(self, user_id: int, role: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE bridge_users SET role = ? WHERE user_id = ?", (role, user_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        # المالك Moaz
        if user_id in [5620024477]:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM bridge_users WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                if row:
                    return dict(row)
            return {
                "user_id": 5620024477,
                "username": "VIPSTORE1S",
                "full_name": "MOAZ",
                "role": "OWNER",
                "is_active": 1,
                "created_at": ""
            }
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bridge_users WHERE user_id = ? AND is_active = 1", (user_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def is_user_allowed(self, user_id: int) -> bool:
        # المالك Moaz مصرح له دائماً
        if user_id in [5620024477]:
            return True
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM bridge_users WHERE user_id = ? AND is_active = 1", (user_id,))
            return cursor.fetchone() is not None

    def list_allowed_users(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bridge_users WHERE is_active = 1 ORDER BY user_id ASC")
            return [dict(r) for r in cursor.fetchall()]


# كائن قاعدة البيانات العام
db = BridgeDatabase()
