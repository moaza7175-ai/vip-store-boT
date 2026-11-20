"""
queue_manager.py - نظام الطابور وتتبع العمليات وربط الردود
Transaction Queue, Correlation Engine & Response Dispatcher
Ensures zero cross-talk between transactions, handles sequential multi-message replies,
manages timeouts, and coordinates button clicks bidirectionally.
"""

import asyncio
import time
import logging
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime

from config import DEFAULT_REPLY_TIMEOUT_SECONDS, QUEUE_SETTLE_SECONDS, DEFAULT_DESTINATION_BOT
from bridge_database import db
from bridge_models import TransactionStatus, MessageDirection, MessageType
from telethon_client import telethon_manager

logger = logging.getLogger(__name__)


class QueueManager:
    """إدارة طابور العمليات والتأكد من مطابقة الردود بالعمليات الصحيحة"""

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.current_txn: Optional[Dict[str, Any]] = None
        self.last_txn: Optional[Dict[str, Any]] = None
        self.last_txn_time: float = 0.0
        self._button_active_txn: Optional[Dict[str, Any]] = None
        self._button_active_until: float = 0.0
        self._worker_task: Optional[asyncio.Task] = None
        self._reply_event: asyncio.Event = asyncio.Event()

        # دالة الإرسال إلى المستخدم عبر البوت الأساسي (Primary Bot Dispatcher)
        self._primary_bot_dispatcher: Optional[Callable] = None

    def set_primary_bot_dispatcher(self, dispatcher_cb: Callable):
        """تعيين دالة إرسال الرسائل إلى المستخدم عبر البوت الأساسي"""
        self._primary_bot_dispatcher = dispatcher_cb

    def start(self):
        """بدء عامل تشغيل الطابور في الخلفية"""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._queue_worker())
            telethon_manager.set_reply_callback(self.handle_inbound_reply)
            logger.info("تم بدء مشغل طابور العمليات (Queue Worker).")

    async def enqueue_link(self, txn_data: Dict[str, Any]):
        """إضافة عملية جديدة إلى الطابور"""
        await self.queue.put(txn_data)
        logger.info(f"تمت إضافة العملية {txn_data['transaction_id']} إلى الطابور (العدد المتبقي: {self.queue.qsize()})")

    async def _queue_worker(self):
        """حلقة العمل المستمرة لمعالجة الروابط بالتتابع لمنع أي اختلاط في الردود"""
        while True:
            try:
                txn = await self.queue.get()
                self.current_txn = txn
                txn_id = txn["transaction_id"]

                logger.info(f"جاري معالجة العملية: {txn_id} | الرابط: {txn['original_link']}")

                # 1. تحديث الحالة إلى SENDING
                db.update_transaction(txn_id, {"status": TransactionStatus.SENDING.value})
                if self._primary_bot_dispatcher:
                    await self._primary_bot_dispatcher(
                        chat_id=txn["chat_id"],
                        event_type="SENDING",
                        txn=txn,
                        text="⏳ <b>جاري إرسال الرابط إلى البوت المستقبِل عبر حسابك الشخصي...</b>"
                    )

                # 2. إرسال الرابط عبر Telethon
                target_bot = txn.get("destination_bot") or db.get_setting("default_destination", DEFAULT_DESTINATION_BOT)
                try:
                    sent_msg_id = await telethon_manager.send_to_target(target_bot, txn["original_link"])
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    # تسجيل رسالة الإرسال الصادرة
                    db.save_message({
                        "transaction_id": txn_id,
                        "direction": MessageDirection.OUTBOUND.value,
                        "message_type": MessageType.TEXT.value,
                        "text_content": txn["original_link"],
                        "telegram_message_id": sent_msg_id
                    })

                    db.update_transaction(txn_id, {
                        "status": TransactionStatus.WAITING_FOR_REPLY.value,
                        "sent_out_message_id": sent_msg_id,
                        "sent_at": now_str
                    })

                    if self._primary_bot_dispatcher:
                        await self._primary_bot_dispatcher(
                            chat_id=txn["chat_id"],
                            event_type="SENT",
                            txn=txn,
                            text=f"✅ <b>تم إرسال الرابط بنجاح إلى @{target_bot}.</b>\n<i>في انتظار وصول الرد...</i>"
                        )

                except Exception as send_err:
                    err_msg = f"فشل إرسال الرابط: {send_err}"
                    logger.error(f"خطأ أثناء إرسال الرابط للعملية {txn_id}: {send_err}")
                    db.update_transaction(txn_id, {
                        "status": TransactionStatus.FAILED.value,
                        "error_message": str(send_err)
                    })
                    if self._primary_bot_dispatcher:
                        await self._primary_bot_dispatcher(
                            chat_id=txn["chat_id"],
                            event_type="FAILED",
                            txn=txn,
                            text=f"❌ <b>فشل إرسال الرابط:</b> <code>{send_err}</code>"
                        )
                    self.current_txn = None
                    self.queue.task_done()
                    continue

                # 3. انتظار وصول الرد مع ضبط مهلة الانتظار (Timeout)
                timeout_sec = int(db.get_setting("reply_timeout_seconds", str(DEFAULT_REPLY_TIMEOUT_SECONDS)))
                self._reply_event.clear()

                try:
                    # ننتظر أول رد
                    await asyncio.wait_for(self._reply_event.wait(), timeout=timeout_sec)

                    # بمجرد وصول أول رد، ننتظر فترة استقرار كاملة لمدة 20 ثانية لجمع ونقل كافة الردود والرسائل المتتالية
                    settle_sec = float(db.get_setting("queue_settle_seconds", "20.0"))
                    logger.info(f"العملية {txn_id}: تم استلام رد، جاري استمرار استقبال الردود لمدة {settle_sec} ثانية...")
                    await asyncio.sleep(settle_sec)

                    db.update_transaction(txn_id, {"status": TransactionStatus.COMPLETED.value})
                    if self._primary_bot_dispatcher:
                        await self._primary_bot_dispatcher(
                            chat_id=txn["chat_id"],
                            event_type="COMPLETED",
                            txn=txn,
                            text="✅ <b>اكتمل استقبال كافة الردود بنجاح (خلال نافذة 20 ثانية).</b>"
                        )

                except asyncio.TimeoutError:
                    logger.warning(f"انتهت مهلة انتظار رد العملية {txn_id} دون استجابة (Timeout)")
                    db.update_transaction(txn_id, {
                        "status": TransactionStatus.TIMEOUT.value,
                        "error_message": f"تجاوز مهلة الانتظار ({timeout_sec} ثانية)"
                    })
                    if self._primary_bot_dispatcher:
                        await self._primary_bot_dispatcher(
                            chat_id=txn["chat_id"],
                            event_type="TIMEOUT",
                            txn=txn,
                            text=f"⚠️ <b>تجاوز مهلة انتظار الرد:</b> لم يستجب البوت المستقبِل خلال {timeout_sec} ثانية."
                        )

            except Exception as e:
                logger.error(f"خطأ غير متوقع في طابور العمليات: {e}")

            finally:
                self.last_txn = self.current_txn
                self.last_txn_time = time.time()
                self.current_txn = None
                self.queue.task_done()

    async def handle_inbound_reply(self, reply_payload: Dict[str, Any]):
        """
        معالجة الرد الوارد من البوت المستقبِل وربطه بالعملية النشطة الحالية
        وإعادة توجيهه فوراً إلى المستخدم عبر البوت الأساسي خلال نافذة الـ 20 ثانية
        """
        now_ts = time.time()
        active_txn = self.current_txn

        # فحص هل هناك تفاعل أزرار نشط خلال نافذة الـ 20 ثانية
        if not active_txn and self._button_active_txn and (now_ts < self._button_active_until):
            active_txn = self._button_active_txn

        # فحص هل وصل الرد بعد انتهاء العملية (نربطه بآخر عملية نشطة للمستخدم)
        if not active_txn and self.last_txn:
            active_txn = self.last_txn
            logger.info(f"تم توجيه الرد المتأخر إلى العملية الأخيرة: {active_txn['transaction_id']}")

        if not active_txn:
            logger.warning("وصل رد من البوت المستقبِل ولكن لا توجد عملية مسجلة إطلاقاً.")
            db.record_log(
                "UNMATCHED_REPLY",
                f"وصل رد غير مرتبط بعملية: {reply_payload.get('text_content', '')[:100]}",
                level="WARNING"
            )
            return

        txn_id = active_txn["transaction_id"]
        reply_payload["transaction_id"] = txn_id

        # حفظ الرسالة الواردة في قاعدة البيانات
        db.save_message(reply_payload)
        db.record_log("REPLY_RECEIVED", f"وصل رد للعملية {txn_id}", txn_id=txn_id)

        # إشعار الطابور بأن أول رد قد وصل
        self._reply_event.set()

        # إرسال محتوى الرد (نص، صورة، ملف، أزرار) فوراً إلى المستخدم عبر البوت الأساسي
        if self._primary_bot_dispatcher:
            await self._primary_bot_dispatcher(
                chat_id=active_txn["chat_id"],
                event_type="INBOUND_REPLY",
                txn=active_txn,
                reply=reply_payload
            )

    async def trigger_button_click(self, txn_id: str, row: int, col: int, data: Optional[str] = None, user_id: int = 0) -> bool:
        """
        التعامل مع ضغط المستخدم على زر تفاعلي في البوت الأساسي وإرساله للبوت المستقبِل
        وفتح نافذة 20 ثانية لاستقبال كافة الردود الناتجة عن الضغط
        """
        txn = db.get_transaction(txn_id)
        if not txn:
            return False

        # فتح نافذة استقبال الردود لمدة 20 ثانية لهذا التفاعل
        self._button_active_txn = txn
        self._button_active_until = time.time() + 20.0

        target_bot = txn.get("destination_bot") or db.get_setting("default_destination", DEFAULT_DESTINATION_BOT)
        sent_msg_id = txn.get("sent_out_message_id")

        # البحث عن معرف رسالة الرد الأخيرة التي تحتوي على الأزرار
        messages = txn.get("messages", [])
        last_msg_with_btn = None
        for m in reversed(messages):
            if m.get("has_buttons") and m.get("telegram_message_id"):
                last_msg_with_btn = m["telegram_message_id"]
                break

        target_message_id = last_msg_with_btn or sent_msg_id
        if not target_message_id:
            logger.warning(f"تعذر تحديد الرسالة المستهدفة للضغط على الزر في العملية {txn_id}")
            return False

        success = await telethon_manager.click_button(target_bot, target_message_id, row, col, data)
        db.record_callback({
            "transaction_id": txn_id,
            "button_label": f"Row {row}, Col {col}",
            "button_data": data or "",
            "button_row": row,
            "button_col": col,
            "clicked_by_user_id": user_id,
            "click_status": "SUCCESS" if success else "FAILED"
        })
        return success


# كائن مدير الطابور العام
queue_manager = QueueManager()
