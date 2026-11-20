"""
bot.py - البوت الرسمي لنظام VIP STORE ADMINS
VIP STORE – Smart Missing Data Assistant
نظام ذكي متكامل يعمل برسالتين نصيتين فقط لكل عملية:
1. الرسالة الأولى: تفاصيل الطلب والحساب المالي.
2. الرسالة الثانية: التقرير المالي العام التراكمي المثبت في الجروب.
المخرجات نصية نقية فقط (ممنوع أي صور أو PDF أو ملفات).
استقبال ذكي للطلبات مع فحص البيانات الناقصة وإمكانية إضافتها أو تخطيها واعتمادها بسلاسة.
"""

import io
import re
import logging
from pathlib import Path
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from config import BOT_TOKEN, VIP_ADMINS_GROUP_ID, OUTPUT_DIR
from database import db
from models import Invoice
from template_engine import render_invoice_image, render_invoice_pdf
from order_parser import (
    is_order_message,
    inspect_missing_data,
    update_order_with_text,
    clean_marketing_noise,
)

# إعداد السجلات (Logging)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- تكامل VIP STORE LINK BRIDGE (تحويل روابط ميداسباي بحساب تيليجرام الشخصي) ---
import sys
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    from link_detector import extract_links, has_links, generate_transaction_id, deduplicator
    from telethon_client import telethon_manager
    from queue_manager import queue_manager
    from bridge_models import TransactionStatus, MessageType as BridgeMessageType
    import bridge_database as bridge_db_module
    bridge_db = bridge_db_module.db
    BRIDGE_AVAILABLE = True
    logger.info("تم تحميل موديول VIP STORE LINK BRIDGE بنجاح.")
except Exception as e:
    logger.warning(f"تعذر تحميل موديول LINK BRIDGE: {e}")
    BRIDGE_AVAILABLE = False

bot_instance = None


def format_role_title(role: str) -> str:
    """تنسيق مسمى الرتبة بأيقونة أنيقة"""
    r = (role or "").strip().upper()
    if r in ["OWNER", "المالك", "مالك"]:
        return "👑 مالك النظام (Owner)"
    elif r in ["SUPER_ADMIN", "مشرف عام", "مدير عام", "SUPERADMIN"]:
        return "🛡️ مشرف عام (Super Admin)"
    elif r in ["ADMIN", "مشرف", "أدمن", "ادمن"]:
        return "⚡ مشرف (Admin)"
    elif r in ["MEMBER", "عضو", "عضو مصرح", "ALLOWED"]:
        return "⭐ عضو مصرح (VIP Member)"
    else:
        return f"🎖️ {role}"


def normalize_role_input(role_input: str) -> str:
    """توحيد أسماء الرتب المدخلة"""
    if not role_input:
        return "ADMIN"
    clean = role_input.strip()
    c_lower = clean.lower()
    if c_lower in ["owner", "مالك", "المالك"]:
        return "OWNER"
    elif c_lower in ["super_admin", "superadmin", "مشرف عام", "مدير عام"]:
        return "SUPER_ADMIN"
    elif c_lower in ["admin", "مشرف", "أدمن", "ادمن"]:
        return "ADMIN"
    elif c_lower in ["member", "allowed", "عضو", "عضو مصرح", "مصرح"]:
        return "MEMBER"
    return clean


async def bridge_dispatch_to_user(chat_id: int, event_type: str, txn: dict, text: str = None, reply: dict = None):
    """إرسال إشعارات ونتائج تحويل الروابط من البوت المستهدف إلى محادثة المستخدم مع إظهار المرسل ورتبته"""
    global bot_instance
    if not bot_instance:
        return

    txn_id = txn.get("transaction_id", "")
    target_bot = txn.get("destination_bot") or (bridge_db.get_setting("default_destination", "MidasbuyHelp_bot") if BRIDGE_AVAILABLE else "MidasbuyHelp_bot")

    uid = txn.get("user_id")
    user_record = bridge_db.get_user(uid) if (BRIDGE_AVAILABLE and uid) else {}
    role = txn.get("sender_role") or (user_record.get("role") if user_record else ("OWNER" if uid == 5620024477 else "ADMIN"))
    role_title = txn.get("sender_role_title") or format_role_title(role)
    s_name = txn.get("sender_name") or (user_record.get("full_name") if user_record else "مستخدم")
    s_user = txn.get("sender_username") or (user_record.get("username") if user_record else "")
    s_display = f"<b>{s_name}</b>" + (f" (@{s_user})" if s_user else "")

    sender_header_info = (
        f"👤 <b>المرسل:</b> {s_display}\n"
        f"🎖️ <b>الرتبة:</b> {role_title}\n"
    )

    try:
        if event_type in ["SENDING", "SENT", "TIMEOUT", "FAILED", "COMPLETED"]:
            if text:
                if "المرسل:" not in text:
                    text_to_send = f"{text}\n{sender_header_info.strip()}"
                else:
                    text_to_send = text
                await bot_instance.send_message(chat_id=chat_id, text=text_to_send, parse_mode="HTML")
            return

        if event_type == "INBOUND_REPLY" and reply:
            reply_text = reply.get("text_content") or ""
            msg_type = reply.get("message_type") or "TEXT"
            media_path = reply.get("media_path")
            raw_buttons = reply.get("raw_buttons")

            reply_markup = None
            if raw_buttons:
                inline_rows = []
                for row in raw_buttons:
                    btn_row = []
                    for btn in row:
                        if getattr(btn, "url", None):
                            btn_row.append(InlineKeyboardButton(text=btn.label, url=btn.url))
                        else:
                            cb_data = f"brg_{txn_id}_{btn.row}_{btn.col}"
                            btn_row.append(InlineKeyboardButton(text=btn.label, callback_data=cb_data))
                    if btn_row:
                        inline_rows.append(btn_row)
                if inline_rows:
                    reply_markup = InlineKeyboardMarkup(inline_rows)

            orig_link = txn.get("original_link", "")
            link_snippet = f"🔗 <b>الرابط:</b> <code>{orig_link}</code>\n" if orig_link else ""
            header = (
                f"📩 <b>رد جديد من @{target_bot}</b> 👑\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{sender_header_info}"
                f"{link_snippet}"
                f"━━━━━━━━━━━━━━━━━━━━\n"
            )

            if msg_type == "PHOTO" and media_path and Path(media_path).exists():
                caption = f"{header}{reply_text}" if reply_text else header
                with open(media_path, "rb") as photo_f:
                    await bot_instance.send_photo(
                        chat_id=chat_id,
                        photo=photo_f,
                        caption=caption[:1024],
                        parse_mode="HTML",
                        reply_markup=reply_markup
                    )
            elif msg_type == "DOCUMENT" and media_path and Path(media_path).exists():
                caption = f"{header}{reply_text}" if reply_text else header
                with open(media_path, "rb") as doc_f:
                    await bot_instance.send_document(
                        chat_id=chat_id,
                        document=doc_f,
                        caption=caption[:1024],
                        parse_mode="HTML",
                        reply_markup=reply_markup
                    )
            else:
                full_msg = f"{header}{reply_text}" if reply_text else f"{header}<i>(تم استقبال رد فارغ أو وسائط غير مدعومة)</i>"
                await bot_instance.send_message(
                    chat_id=chat_id,
                    text=full_msg,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
    except Exception as e:
        logger.error(f"خطأ أثناء إرسال رد وسيط الروابط للمستخدم {chat_id}: {e}")


async def on_bridge_startup(application: Application):
    """تهيئة وتشغيل وسيط تيليجرام Telethon وطابور العمليات تلقائياً عند تشغيل البوت"""
    global bot_instance
    bot_instance = application.bot
    if not BRIDGE_AVAILABLE:
        return
    logger.info("Initializing Link Bridge via Telethon & Queue Worker...")
    try:
        acc_connected = await telethon_manager.initialize()
        if acc_connected:
            logger.info("Telethon personal account connected successfully (@VIPSTORE1S).")
        else:
            logger.warning("Telethon personal account not connected yet.")
        queue_manager.set_primary_bot_dispatcher(bridge_dispatch_to_user)
        queue_manager.start()
        logger.info("VIP STORE LINK BRIDGE is running in unified bot!")
    except Exception as e:
        logger.error(f"Error starting Link Bridge: {e}")


async def on_bridge_shutdown(application: Application):
    """إغلاق اتصالات وسيط الروابط بأمان عند إيقاف البوت"""
    if BRIDGE_AVAILABLE:
        try:
            await telethon_manager.disconnect()
        except Exception:
            pass



# =============================================================================
#  تنسيق الرسالتين النصيتين لجروب VIP STORE ADMINS
# =============================================================================

def format_order_financial_message(inv_data: dict) -> str:
    """
    الرسالة الأولى: تفاصيل الطلب والحساب المالي
    - رقم الطلب والتاريخ.
    - اسم العميل والمنتج.
    - بيانات الحساب (اسم الحساب و ID).
    - الإيرادات.
    - التكلفة.
    - المصروفات.
    - الخسائر.
    - صافي ربح أو خسارة الطلب.
    """
    order_num = inv_data.get("order_number", "—")
    date_str = inv_data.get("date", datetime.now().strftime("%Y-%m-%d %H:%M"))
    cust_name = inv_data.get("customer_name") or "—"
    cust_phone = inv_data.get("customer_phone", "")
    acc_name = inv_data.get("account_name") or "—"
    player_id = inv_data.get("player_id") or "—"
    prod_name = inv_data.get("product_name") or "شحن ألعاب"
    qty = float(inv_data.get("quantity") or 1.0)

    revenue = float(inv_data.get("total_amount", 0.0) or inv_data.get("total", 0.0))
    cost = float(inv_data.get("cost", 0.0))
    expenses = float(inv_data.get("expenses", 0.0))
    losses = float(inv_data.get("losses", 0.0))
    net_profit = float(inv_data.get("net_profit", revenue - cost - expenses - losses))

    phone_line = f"\n• <b>الهاتف:</b> <code>{cust_phone}</code>" if cust_phone else ""

    if net_profit > 0:
        profit_badge = f"🟢 <b>صافي ربح الطلب:</b> <b>+{net_profit:,.2f} ج.م</b>"
    elif net_profit < 0:
        profit_badge = f"🔴 <b>صافي خسارة الطلب:</b> <b>{net_profit:,.2f} ج.م</b>"
    else:
        profit_badge = f"⚪ <b>صافي الربح:</b> <b>0.00 ج.م (نقطة تعادل)</b>"

    msg = (
        f"🧾 <b>تفاصيل الطلب والحساب المالي</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔢 <b>رقم الطلب:</b> <code>#{order_num}</code>\n"
        f"📅 <b>التاريخ:</b> <code>{date_str}</code>\n"
        f"👤 <b>العميل:</b> {cust_name}{phone_line}\n"
        f"🎮 <b>بيانات الطلب:</b>\n"
        f"• <b>المنتج / الباقة:</b> <b>{prod_name}</b> (الكمية: {qty:g})\n"
        f"• <b>اسم الحساب:</b> <code>{acc_name}</code>\n"
        f"• <b>ID الحساب:</b> <code>{player_id}</code>\n"
        f"────────────────────\n"
        f"💵 <b>الإيرادات (سعر البيع):</b> {revenue:,.2f} ج.م\n"
        f"🛒 <b>التكلفة (سعر الشراء):</b> {cost:,.2f} ج.م\n"
        f"🧾 <b>المصروفات:</b> {expenses:,.2f} ج.م\n"
        f"📉 <b>الخسائر:</b> {losses:,.2f} ج.م\n"
        f"────────────────────\n"
        f"{profit_badge}"
    )
    return msg


def format_cumulative_report_message(metrics: dict) -> str:
    """
    الرسالة الثانية: التقرير المالي العام (المثبتة في الجروب)
    - إجمالي الإيرادات.
    - إجمالي التكاليف.
    - إجمالي المصروفات.
    - إجمالي الخسائر.
    - صافي الربح الكلي التراكمي.
    - عدد الطلبات.
    - تاريخ آخر تحديث.
    """
    total_orders = metrics.get("total_orders", 0)
    total_rev = metrics.get("total_revenue", 0.0)
    total_cost = metrics.get("total_cost", 0.0)
    total_exp = metrics.get("total_expenses", 0.0)
    total_losses = metrics.get("total_losses", 0.0)
    total_profit = metrics.get("total_net_profit", 0.0)
    last_updated = metrics.get("last_updated") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    margin = (total_profit / total_rev * 100.0) if total_rev > 0 else 0.0

    if total_profit >= 0:
        profit_line = f"🟢 <b>صافي الربح الكلي التراكمي:</b> <b>+{total_profit:,.2f} ج.م</b>"
    else:
        profit_line = f"🔴 <b>صافي الخسارة الكلية التراكمية:</b> <b>{total_profit:,.2f} ج.م</b>"

    msg = (
        f"📊 <b>VIP STORE – GAMING SERVICES</b>\n"
        f"👑 <b>التقرير المالي العام (الحسابات التراكمية)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>عدد الطلبات المسجلة:</b> <b>{total_orders}</b> طلب\n"
        f"────────────────────\n"
        f"💵 <b>إجمالي الإيرادات:</b> {total_rev:,.2f} ج.م\n"
        f"🛒 <b>إجمالي التكاليف:</b> {total_cost:,.2f} ج.م\n"
        f"🧾 <b>إجمالي المصروفات:</b> {total_exp:,.2f} ج.م\n"
        f"📉 <b>إجمالي الخسائر:</b> {total_losses:,.2f} ج.م\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{profit_line} ({margin:.1f}%)\n"
        f"────────────────────\n"
        f"🕒 <b>تاريخ آخر تحديث:</b> <code>{last_updated}</code>\n\n"
        f"📌 <i>هذه الرسالة مثبتة في الجروب ويتم تحديثها تلقائياً مع كل عملية جديدة.</i>"
    )
    return msg


async def execute_two_messages_protocol(bot, target_chat_id: int | str, order_data: dict):
    """
    إرسال الرسالة الأولى وتحديث الرسالة الثانية المثبتة تلقائياً
    """
    # 1. إرسال الرسالة الأولى: تفاصيل الطلب والحساب المالي
    msg1_text = format_order_financial_message(order_data)
    sent_msg1 = await bot.send_message(
        chat_id=target_chat_id,
        text=msg1_text,
        parse_mode="HTML"
    )

    try:
        db.record_telegram_post(
            order_number=order_data["order_number"],
            chat_id=str(target_chat_id),
            chat_title="",
            message_id=sent_msg1.message_id,
            status="SUCCESS"
        )
    except Exception as e:
        logger.warning(f"تعذر تسجيل النشر في جدول telegram_posts: {e}")

    # 2. تحديث الرسالة الثانية المثبتة: التقرير المالي العام
    metrics = db.get_cumulative_metrics()
    report_text = format_cumulative_report_message(metrics)

    pinned_msg_id = db.get_setting("pinned_report_message_id")
    pinned_chat_id = db.get_setting("pinned_report_chat_id")

    updated = False
    if pinned_msg_id and pinned_chat_id and str(pinned_chat_id) == str(target_chat_id):
        try:
            await bot.edit_message_text(
                chat_id=target_chat_id,
                message_id=int(pinned_msg_id),
                text=report_text,
                parse_mode="HTML"
            )
            updated = True
            logger.info(f"تم تحديث الرسالة المثبتة بنجاح #{pinned_msg_id}")
        except Exception as e:
            logger.warning(f"تعذر تعديل الرسالة المثبتة الحالية: {e}، سيتم إنشاء رسالة مثبتة جديدة")

    if not updated:
        sent_report = await bot.send_message(
            chat_id=target_chat_id,
            text=report_text,
            parse_mode="HTML"
        )
        try:
            await bot.pin_chat_message(
                chat_id=target_chat_id,
                message_id=sent_report.message_id,
                disable_notification=True
            )
            logger.info(f"تم تثبيت رسالة التقرير بنجاح #{sent_report.message_id}")
        except Exception as e:
            logger.warning(f"تعذر تثبيت رسالة التقرير (تأكد من إعطاء البوت صلاحية التثبيت): {e}")

        db.set_setting("pinned_report_message_id", str(sent_report.message_id))
        db.set_setting("pinned_report_chat_id", str(target_chat_id))


def get_target_group_id(update: Update) -> str:
    """تحديد الجروب المستهدف للرسالتين"""
    chat = update.effective_chat
    if chat and chat.type in ["group", "supergroup"]:
        return str(chat.id)

    saved_group = db.get_setting("vip_admins_group_id")
    if saved_group:
        return saved_group
    if VIP_ADMINS_GROUP_ID:
        return VIP_ADMINS_GROUP_ID

    return str(chat.id)


# =============================================================================
#  VIP STORE – Smart Missing Data Assistant Flow
# =============================================================================

def format_missing_data_prompt(inspection: dict) -> tuple[str, InlineKeyboardMarkup]:
    """
    صياغة رسالة فحص البيانات الناقصة بالصيغة المطلوبة بالضبط
    """
    order_data = inspection["order_data"]
    order_num = order_data.get("order_number") or ""
    avail = inspection["available_fields"]
    missing = inspection["missing_fields"]

    avail_lines = [f"- {item['label']}: {item['val']}" for item in avail]
    missing_lines = [f"- {item['label']}" for item in missing]

    title = f"الطلب #{order_num}" if order_num else "طلب الشحن الجديد"

    msg = (
        f"📋 <b>تم استلام {title} بنجاح.</b>\n\n"
        f"✅ <b>البيانات المتوفرة:</b>\n" + "\n".join(avail_lines) + "\n\n"
        f"⚠️ <b>بيانات إضافية غير موجودة:</b>\n" + "\n".join(missing_lines) + "\n\n"
        f"هل تريد إضافة بيانات أخرى قبل إنشاء الفاتورة؟"
    )

    buttons = [
        [InlineKeyboardButton("➕ إضافة بيانات ناقصة", callback_data="btn_add_missing")],
        [InlineKeyboardButton("⏭️ تخطي واستكمال الفاتورة بالبيانات المتوفرة", callback_data="btn_skip_missing")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="btn_cancel_order")],
    ]
    return msg, InlineKeyboardMarkup(buttons)


def format_missing_fields_menu(inspection: dict) -> tuple[str, InlineKeyboardMarkup]:
    """
    عرض قائمة الأزرار للحقول الناقصة فقط
    """
    missing = inspection["missing_fields"]
    order_num = inspection["order_data"].get("order_number") or ""
    title_suffix = f" للطلب #{order_num}" if order_num else ""

    field_buttons_map = {
        "order_number": "🔢 رقم الطلب",
        "customer_name": "👤 اسم العميل",
        "account_name": "🎮 اسم الحساب",
        "player_id": "🆔 ID الحساب",
        "quantity": "🔢 الكمية",
        "cost": "🛒 التكلفة",
        "profit": "📈 الأرباح",
        "losses": "📉 الخسائر",
        "total_amount": "💵 الإجمالي",
        "product_name": "📦 الباقة / المنتج",
        "date": "📅 التاريخ",
    }

    buttons = []
    row = []
    for m in missing:
        key = m["key"]
        btn_text = field_buttons_map.get(key, f"➕ {m['label']}")
        row.append(InlineKeyboardButton(btn_text, callback_data=f"field_{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("⏭️ استكمال الفاتورة والاعتماد", callback_data="btn_skip_missing")])
    buttons.append([InlineKeyboardButton("❌ إلغاء", callback_data="btn_cancel_order")])

    msg = (
        f"✏️ <b>إضافة بيانات{title_suffix}:</b>\n"
        f"اختر الحقل الذي تريد إضافته (كل الحقول اختيارية):\n\n"
        f"💡 <i>يمكنك أيضاً إرسال البيانات مباشرة كنص، مثلاً:</i>\n"
        f"<code>العميل: محمد علي\nالحساب: VIP_Player\nID: 55443322</code>"
    )
    return msg, InlineKeyboardMarkup(buttons)


def format_review_summary(order_data: dict) -> tuple[str, InlineKeyboardMarkup]:
    """
    الخطوة 6: عرض ملخص المراجعة والاعتماد النهائي
    """
    order_num = order_data.get("order_number", "—")
    date_str = order_data.get("date", "—")
    cust_name = order_data.get("customer_name") or "—"
    acc_name = order_data.get("account_name") or "—"
    player_id = order_data.get("player_id") or "—"
    prod_name = order_data.get("product_name") or "شحن ألعاب"
    qty = float(order_data.get("quantity") or 1.0)

    rev = float(order_data.get("total_amount", 0.0))
    cost = float(order_data.get("cost", 0.0))
    exp = float(order_data.get("expenses", 0.0))
    losses = float(order_data.get("losses", 0.0))
    net_profit = float(order_data.get("net_profit", rev - cost - exp - losses))

    margin = (net_profit / rev * 100.0) if rev > 0 else 0.0

    if net_profit > 0:
        profit_badge = f"🟢 <b>صافي الربح:</b> <b>+{net_profit:,.2f} ج.م</b> (+{margin:.1f}%)"
    elif net_profit < 0:
        profit_badge = f"🔴 <b>صافي الخسارة:</b> <b>{net_profit:,.2f} ج.م</b> ({margin:.1f}%)"
    else:
        profit_badge = f"⚪ <b>صافي الربح:</b> <b>0.00 ج.م (نقطة تعادل)</b>"

    msg = (
        f"📋 <b>ملخص مراجعة الفاتورة قبل الاعتماد:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔢 <b>رقم الطلب:</b> <code>#{order_num}</code>\n"
        f"📅 <b>التاريخ:</b> <code>{date_str}</code>\n"
        f"👤 <b>العميل:</b> {cust_name}\n"
        f"🎮 <b>اسم الحساب:</b> <code>{acc_name}</code>\n"
        f"🆔 <b>ID الحساب:</b> <code>{player_id}</code>\n"
        f"📦 <b>المنتج / الباقة:</b> <b>{prod_name}</b> (الكمية: {qty:g})\n\n"
        f"💵 <b>التفاصيل المالية:</b>\n"
        f"• <b>الإيرادات (سعر البيع):</b> {rev:,.2f} ج.م\n"
        f"• <b>التكلفة (سعر الشراء):</b> {cost:,.2f} ج.م\n"
        f"• <b>المصروفات:</b> {exp:,.2f} ج.م\n"
        f"• <b>الخسائر:</b> {losses:,.2f} ج.م\n"
        f"────────────────────\n"
        f"{profit_badge}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"هل تعتمد تسجيل الفاتورة نهائياً؟"
    )

    buttons = [
        [InlineKeyboardButton("✅ اعتماد وتسجيل الفاتورة", callback_data="btn_confirm_approve")],
        [InlineKeyboardButton("✏️ تعديل / إضافة بيانات", callback_data="btn_add_missing")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="btn_cancel_order")],
    ]
    return msg, InlineKeyboardMarkup(buttons)


# =============================================================================
#  لوحات الأزرار التفاعلية (Keyboard & Control Panel)
# =============================================================================

def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """لوحة الأزرار الرئيسية الثابتة أسفل الشاشة بلمسة واحدة"""
    keyboard = [
        [KeyboardButton("📊 التقرير المالي العام"), KeyboardButton("📦 أحدث الطلبات")],
        [KeyboardButton("📑 استخراج فاتورة عميل"), KeyboardButton("📥 تصدير سجل Excel")],
        [KeyboardButton("⚡ وسيط روابط Midasbuy"), KeyboardButton("ℹ️ دليل واستخدام النظام")],
        [KeyboardButton("📌 تثبيت التقرير بالجروب"), KeyboardButton("⚙️ لوحة التحكم")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_control_panel_keyboard() -> InlineKeyboardMarkup:
    """لوحة التحكم التفاعلية المدمجة كأزرار داخل الرسائل"""
    buttons = [
        [
            InlineKeyboardButton("📊 التقرير المالي العام", callback_data="cmd_report"),
            InlineKeyboardButton("📦 أحدث الطلبات", callback_data="cmd_orders"),
        ],
        [
            InlineKeyboardButton("📑 استخراج فاتورة عميل", callback_data="cmd_get_invoice"),
            InlineKeyboardButton("📥 تصدير سجل Excel", callback_data="cmd_export"),
        ],
        [
            InlineKeyboardButton("⚡ حالة وسيط الروابط", callback_data="cmd_bridge_status"),
            InlineKeyboardButton("🤖 بوتات الاستلام", callback_data="cmd_bots_list"),
        ],
        [
            InlineKeyboardButton("👥 طاقم الإدارة والرتب", callback_data="cmd_allowed_users"),
            InlineKeyboardButton("📌 تثبيت التقرير بالجروب", callback_data="cmd_pinreport"),
        ],
        [
            InlineKeyboardButton("ℹ️ دليل واستخدام النظام", callback_data="cmd_help"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


async def send_invoice_by_order(chat_id: int | str, bot, order_num: str) -> bool:
    """استخراج وإرسال صورة و PDF فاتورة العميل مباشرة"""
    clean_order = order_num.strip().replace("#", "")
    inv_dict = db.get_invoice_by_order(clean_order)
    if not inv_dict:
        await bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ <b>لم يتم العثور على طلب مسجل برقم:</b> <code>#{clean_order}</code>",
            parse_mode="HTML"
        )
        return False

    invoice = Invoice.from_dict(inv_dict)
    img_bytes = render_invoice_image(invoice)
    pdf_bytes = render_invoice_pdf(invoice)

    clean_file_id = re.sub(r'[^\w\-]', '_', clean_order)
    cust_name = inv_dict.get("customer_name") or "—"
    acc_name = inv_dict.get("account_name") or "—"
    player_id = inv_dict.get("player_id") or "—"
    prod_name = invoice.items[0].name if invoice.items else "شحن ألعاب"
    tot_amount = float(inv_dict.get("total_amount", 0.0))

    caption = (
        f"📄 <b>فاتورة العميل الرسمية - طلب #{clean_order}</b> 👑\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>اسم العميل:</b> {cust_name}\n"
        f"🎮 <b>اسم الحساب:</b> <code>{acc_name}</code>\n"
        f"🆔 <b>ID الحساب:</b> <code>{player_id}</code>\n"
        f"📦 <b>الباقة:</b> {prod_name}\n"
        f"💵 <b>المبلغ المطلوب:</b> {tot_amount:,.2f} ج.م\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <i>جاهزة للإرسال للعميل مباشرة كصورة أو ملف PDF.</i>"
    )

    await bot.send_photo(
        chat_id=chat_id,
        photo=io.BytesIO(img_bytes),
        caption=caption,
        parse_mode="HTML"
    )
    await bot.send_document(
        chat_id=chat_id,
        document=io.BytesIO(pdf_bytes),
        filename=f"{clean_file_id}.pdf",
        caption=f"📎 <b>ملف PDF الرسمي للطلب:</b> <code>{clean_file_id}.pdf</code>",
        parse_mode="HTML"
    )
    return True


async def send_recent_orders(message):
    """عرض أحدث الطلبات المسجلة"""
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT order_number, date, customer_name, total_amount, net_profit FROM invoices ORDER BY id DESC LIMIT 10")
        rows = cursor.fetchall()

    if not rows:
        await message.reply_text("ℹ️ لا توجد طلبات مسجلة حتى الآن.", parse_mode="HTML")
        return

    lines = ["📦 <b>أحدث الطلبات المسجلة في VIP STORE:</b>\n━━━━━━━━━━━━━━━━━━━━"]
    for r in rows:
        p_badge = "🟢" if r["net_profit"] >= 0 else "🔴"
        lines.append(
            f"• <code>#{r['order_number']}</code> | {r['date']} | {r['customer_name'] or 'عميل'}\n"
            f"  💵 الإجمالي: {r['total_amount']:,.2f} ج.م | {p_badge} صافي الربح: {r['net_profit']:,.2f} ج.م"
        )
    lines.append("\n💡 <i>لاستخراج فاتورة أي طلب، اضغط زر [ 📑 استخراج فاتورة عميل ]</i>")
    await message.reply_text("\n".join(lines), parse_mode="HTML")


async def perform_export(message):
    """تصدير سجل الفواتير والمحاسبة إلى ملف Excel"""
    msg_wait = await message.reply_text(
        "⏳ <b>جاري تجهيز وتصدير سجل العمليات والمحاسبة إلى Excel...</b>",
        parse_mode="HTML"
    )
    try:
        excel_path = db.export_to_excel()
        if excel_path and excel_path.exists():
            with open(excel_path, "rb") as f:
                await message.reply_document(
                    document=f,
                    filename=excel_path.name,
                    caption="📊 <b>سجل VIP STORE المالي والمحاسبي الكامل (Excel)</b> 👑",
                    parse_mode="HTML"
                )
            await msg_wait.delete()
        else:
            await msg_wait.edit_text("⚠️ تعذر إنشاء ملف Excel، تأكد من وجود عمليات مسجلة.")
    except Exception as e:
        await msg_wait.edit_text(f"⚠️ خطأ أثناء التصدير: {e}")


async def send_help_guide(message):
    """إرسال دليل النظام وشرح القسمين"""
    guide_text = (
        "🎮 <b>دليل واستخدام نظام VIP STORE – GAMING SERVICES</b> 👑\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "النظام مقسم إلى <b>قسمين منفصلين ومحددين بدقة:</b>\n\n"
        "1️⃣ <b>القسم الأول: قسم العميل (Customer Facing):</b>\n"
        "• صورة رسمية فائقة الجودة (PNG) على قالب VIP STORE.\n"
        "• ملف PDF رسمي عالي الدقة بحجم A4 باسم الطلب (مثل <code>VIP-A79G7U.pdf</code>).\n"
        "• يشتمل على: رقم الطلب، التاريخ، اسم العميل، بيانات الحساب باللعبة، جدول المنتجات، الإجمالي المطلوب.\n"
        "• <b>خالٍ تماماً من التكاليف أو الأرباح الداخلية</b>، جاهز للإرسال للعميل فوراً.\n\n"
        "2️⃣ <b>القسم الثاني: قسم جروب الإدارة (VIP STORE ADMINS):</b>\n"
        "• <b>الرسالة الأولى:</b> تفاصيل الطلب والحساب المالي الداخلي (سعر الشراء، سعر البيع، المصروفات، الخسائر، صافي الربح).\n"
        "• <b>الرسالة الثانية:</b> التقرير المالي العام التراكمي المثبت في الجروب، يتم تحديثه تلقائياً وتثبيت إجمالي الأرباح بعد كل فاتورة دون تكرار.\n"
        "• مخرجات جروب الإدارة <b>نصية نقية فقط</b>.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👇 <b>استخدم لوحة الأزرار أدناه لتنفيذ أي عملية فوراً بلمسة واحدة:</b>"
    )
    await message.reply_text(
        guide_text,
        parse_mode="HTML",
        reply_markup=get_control_panel_keyboard()
    )


# =============================================================================
#  معالجة الرسائل والأوامر
# =============================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رسالة البداية والترحيب وتفعيل لوحة الأزرار"""
    welcome_text = (
        "🎮 <b>مرحباً بك في النظام الذكي لـ VIP STORE – GAMING SERVICES!</b> 👑\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✨ تم تفعيل <b>لوحة الأزرار السريعة</b> في أسفل الشاشة لتسهيل إدارتك للمتجر بلمسة واحدة:\n\n"
        "📊 <b>التقرير المالي:</b> عرض صافي الأرباح والإيرادات والتكاليف التراكمية.\n"
        "📦 <b>أحدث الطلبات:</b> استعراض العمليات المسجلة وحساباتها.\n"
        "📑 <b>استخراج فاتورة:</b> جلب صورة و PDF فاتورة أي عميل سابق.\n"
        "📥 <b>تصدير Excel:</b> تحميل السجل المالي والمحاسبي بالكامل.\n"
        "📌 <b>تثبيت التقرير:</b> تحديث وتثبيت التقرير في جروب الإدارة.\n\n"
        "📥 <b>لإنشاء فاتورة جديدة:</b> أرسل رسالة الطلب مباشرة وسيقوم المساعد بفحصها فوراً!"
    )
    await update.message.reply_text(
        welcome_text,
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard()
    )
    await update.message.reply_text(
        "⚡ <b>لوحة التحكم السريعة (اختر العملية المطلوبة):</b>",
        parse_mode="HTML",
        reply_markup=get_control_panel_keyboard()
    )


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض لوحة التحكم بالأزرار"""
    await update.message.reply_text(
        "⚡ <b>لوحة تحكم VIP STORE – اختر من الأزرار أدناه:</b>",
        parse_mode="HTML",
        reply_markup=get_control_panel_keyboard()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض دليل النظام"""
    await send_help_guide(update.message)


async def invoice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استرجاع صورة و PDF فاتورة العميل بواسطة رقم الطلب"""
    if not context.args:
        context.user_data["awaiting_invoice_number"] = True
        await update.message.reply_text(
            "✍️ <b>يرجى إرسال رقم الطلب المطلوب استخراج فاتورته الآن:</b>\n"
            "مثال: <code>VIP-A79G7U</code>",
            parse_mode="HTML"
        )
        return

    order_num = context.args[0].strip().replace("#", "")
    await send_invoice_by_order(update.effective_chat.id, context.bot, order_num)


async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تصدير سجل الفواتير والمحاسبة إلى ملف Excel"""
    await perform_export(update.message)


async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض أحدث الطلبات المسجلة"""
    await send_recent_orders(update.message)


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض التقرير المالي العام الحالي"""
    metrics = db.get_cumulative_metrics()
    report_text = format_cumulative_report_message(metrics)
    await update.message.reply_text(report_text, parse_mode="HTML")


async def pinreport_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إنشاء وتثبيت رسالة تقرير جديدة في الجروب الحالي"""
    chat_id = update.effective_chat.id
    metrics = db.get_cumulative_metrics()
    report_text = format_cumulative_report_message(metrics)

    sent_msg = await update.message.reply_text(report_text, parse_mode="HTML")
    try:
        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=sent_msg.message_id,
            disable_notification=True
        )
        db.set_setting("pinned_report_message_id", str(sent_msg.message_id))
        db.set_setting("pinned_report_chat_id", str(chat_id))
        await update.message.reply_text("📌 <b>تم تثبيت رسالة التقرير المالي بنجاح!</b>", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"⚠️ تعذر التثبيت: {e}\n(تأكد من إعطاء البوت صلاحية مشرف لتثبيت الرسائل).", parse_mode="HTML")


async def setgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين الجروب الحالي كجروب VIP STORE ADMINS الرسمي"""
    chat = update.effective_chat
    group_id = context.args[0].strip() if context.args else str(chat.id)

    db.set_setting("vip_admins_group_id", group_id)
    await update.message.reply_text(
        f"✅ <b>تم تعيين الجروب الرسمي لـ VIP STORE ADMINS بنجاح!</b>\n"
        f"🆔 المعرف: <code>{group_id}</code>",
        parse_mode="HTML"
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء أي عملية قيد الانتظار"""
    if "session" in context.user_data:
        del context.user_data["session"]
        await update.message.reply_text("❌ تم إلغاء العملية الحالية.", parse_mode="HTML")
    else:
        await update.message.reply_text("ℹ️ لا توجد عمليات جارية حالياً.", parse_mode="HTML")


# =============================================================================
#  أوامر ومعالجات VIP STORE LINK BRIDGE (وسيط تحويل الروابط)
# =============================================================================

async def forward_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض تقرير مفصل بحالة وسيط تحويل الروابط والحساب الشخصي"""
    target_msg = update.effective_message
    if not BRIDGE_AVAILABLE:
        if target_msg:
            await target_msg.reply_text("⚠️ وسيط الروابط غير متاح حالياً.", parse_mode="HTML")
        return

    forwarding_enabled = bridge_db.get_setting("forwarding_enabled", "true").lower() == "true"
    target_bot = bridge_db.get_setting("default_destination", "MidasbuyHelp_bot")
    timeout_sec = bridge_db.get_setting("reply_timeout_seconds", "60")
    account = bridge_db.get_active_telegram_account()
    stats = bridge_db.get_stats()

    is_conn = telethon_manager._is_connected and account and account.get("session_status") == "CONNECTED"
    status_icon = "🟢 متصل وشغال" if is_conn else "🔴 غير متصل"
    fwd_icon = "🟢 مفعّل تلقائياً" if forwarding_enabled else "🔴 متوقف"

    report = (
        f"👑 <b>حالة نظام وسيط الروابط (VIP STORE LINK BRIDGE):</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📡 <b>حالة التحويل:</b> {fwd_icon}\n"
        f"🎯 <b>البوت المستقبِل:</b> @{target_bot}\n"
        f"⏱️ <b>مهلة انتظار الرد:</b> {timeout_sec} ثانية\n\n"
        f"👤 <b>حساب تيليجرام الشخصي (الوسيط):</b>\n"
        f"• الحالة: {status_icon}\n"
        f"• الاسم: <b>{account.get('first_name', 'MOAZ') if account else 'MOAZ'}</b> (@{account.get('username', 'VIPSTORE1S') if account else 'VIPSTORE1S'})\n"
        f"• الهاتف: <code>{account.get('phone_masked', '+2010****668') if account else '+2010****668'}</code>\n\n"
        f"📊 <b>إحصائيات الروابط:</b>\n"
        f"• إجمالي العمليات: <b>{stats['total_transactions']}</b>\n"
        f"• العمليات المكتملة: <b>{stats['completed']}</b>\n"
        f"• إجمالي الردود: <b>{stats['total_replies']}</b>\n"
        f"• نسبة النجاح: <b>{stats['success_rate']:.1f}%</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 <i>أرسل أي رابط شحن من ميداسباي في أي وقت وسيتم تحويله فوراً وجلب الرد!</i>"
    )
    if target_msg:
        await target_msg.reply_text(report, parse_mode="HTML")


async def forward_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال فحص اتصال تجريبي فوري بين الحساب الشخصي والبوت المستهدف"""
    target_msg = update.effective_message
    if not BRIDGE_AVAILABLE or not telethon_manager._is_connected:
        if target_msg:
            await target_msg.reply_text("🔴 الحساب الشخصي غير متصل حالياً.", parse_mode="HTML")
        return

    msg = await target_msg.reply_text("⏳ جاري اختبار الاتصال بالبوت المستهدف عبر حسابك الشخصي...", parse_mode="HTML")
    res = await telethon_manager.test_connection()
    if res.get("success"):
        await msg.edit_text(
            f"✅ <b>الاتصال ناجح 100%!</b>\n"
            f"👤 حسابك: @{res['username']} (ID: <code>{res['user_id']}</code>)\n"
            f"🎯 البوت المستهدف: @{res['target_bot']} (ID: <code>{res['target_bot_id']}</code>)\n"
            f"🕒 التوقيت: <code>{res['timestamp']}</code>",
            parse_mode="HTML"
        )
    else:
        await msg.edit_text(f"❌ <b>فشل الاختبار:</b> <code>{res.get('error')}</code>", parse_mode="HTML")



async def forward_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bridge_db.set_setting("forwarding_enabled", "true")
    await update.message.reply_text("🟢 <b>تم تفعيل تحويل الروابط تلقائياً.</b>", parse_mode="HTML")


async def forward_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bridge_db.set_setting("forwarding_enabled", "false")
    await update.message.reply_text("🔴 <b>تم إيقاف تحويل الروابط مؤقتاً.</b>", parse_mode="HTML")


async def add_bot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة بوت استلام جديد إلى قائمة البوتات المعتمدة"""
    sender_id = update.effective_user.id
    target_msg = update.effective_message
    if not is_bridge_admin(sender_id):
        await target_msg.reply_text("⛔ هذا الأمر مخصص لمالك البوت والمشرفين العامين فقط.", parse_mode="HTML")
        return

    if not context.args:
        await target_msg.reply_text(
            "✍️ <b>طريقة إضافة بوت استلام جديد:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "اكتب الأمر متبوعاً بيوزرنيم البوت واسمه (اختياري):\n"
            "<code>/add_bot @BotUsername [اسم البوت]</code>\n\n"
            "📌 <b>أمثلة:</b>\n"
            "• <code>/add_bot @MidasbuyHelp_bot بوت شحن ببجي</code>\n"
            "• <code>/add_bot @AnotherBot</code>",
            parse_mode="HTML"
        )
        return

    raw_user = context.args[0].replace("@", "").strip()
    custom_title = " ".join(context.args[1:]).strip() if len(context.args) > 1 else None

    checking_msg = await target_msg.reply_text(f"⏳ <b>جارٍ التحقق من البوت @{raw_user} عبر حسابك الشخصي...</b>", parse_mode="HTML")

    bot_info = await telethon_manager.check_bot_entity(raw_user)
    if not bot_info.get("success"):
        await checking_msg.edit_text(
            f"❌ <b>تعذر العثور على البوت @{raw_user}:</b>\n"
            f"<code>{bot_info.get('error', 'البوت غير موجود أو لا يمكن الوصول إليه')}</code>\n\n"
            f"<i>تأكد من كتابة اليوزرنيم بشكل صحيح وأن البوت متاح في تيليجرام.</i>",
            parse_mode="HTML"
        )
        return

    bot_title = custom_title or bot_info.get("title") or raw_user
    bot_id = bot_info.get("id", "غير معروف")

    bridge_db.add_destination(raw_user, bot_title=bot_title)

    buttons = [
        [
            InlineKeyboardButton("⭐ تعيين كافتراضي الآن", callback_data=f"set_def_bot_{raw_user}"),
            InlineKeyboardButton("🤖 عرض كل البوتات", callback_data="cmd_bots_list")
        ]
    ]

    await checking_msg.edit_text(
        f"🎉 <b>تمت إضافة بوت الاستلام بنجاح!</b> ✅\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 <b>اسم البوت:</b> {bot_title}\n"
        f"🔗 <b>اليوزرنيم:</b> @{raw_user}\n"
        f"🆔 <b>معرف البوت (ID):</b> <code>{bot_id}</code>\n"
        f"⚡ <b>الحالة:</b> متصل وجاهز لاستقبال الروابط وتحويلها فوراً.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def bots_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة بوتات الاستلام المعتمدة وإدارتها"""
    sender_id = update.effective_user.id
    target_msg = update.effective_message
    if not is_bridge_admin(sender_id):
        await target_msg.reply_text("⛔ هذا الأمر مخصص لمالك البوت والمشرفين العامين فقط.", parse_mode="HTML")
        return

    bots = bridge_db.get_destinations()
    default_bot = bridge_db.get_setting("default_destination", "MidasbuyHelp_bot").replace("@", "").lower()

    text = (
        "🤖 <b>قائمة بوتات الاستلام المعتمدة (Destination Bots):</b> 👑\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>البوتات المسجلة التي يقوم حسابك الشخصي بالتحويل إليها وجلب الردود منها:</i>\n\n"
    )

    buttons = []
    for idx, b in enumerate(bots, 1):
        b_user = b["bot_username"]
        b_title = b.get("bot_title") or b_user
        is_def = (b_user.lower() == default_bot) or b.get("is_default")

        badge = "⭐ <b>(الافتراضي النشط حالياً)</b>" if is_def else "⚪ بوت متاح"
        text += f"{idx}. <b>{b_title}</b> (@{b_user})\n   └ {badge}\n\n"

        row_btns = []
        if not is_def:
            row_btns.append(InlineKeyboardButton("⭐ تفعيل كافتراضي", callback_data=f"set_def_bot_{b_user}"))
        row_btns.append(InlineKeyboardButton("🔍 فحص", callback_data=f"test_bot_{b_user}"))
        if len(bots) > 1:
            row_btns.append(InlineKeyboardButton("❌ حذف", callback_data=f"rm_bot_{b_user}"))
        buttons.append(row_btns)

    buttons.append([InlineKeyboardButton("➕ إضافة بوت استلام جديد", callback_data="cmd_prompt_add_bot")])

    text += (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>أوامر سريعة:</b>\n"
        "• لإضافة بوت: <code>/add_bot @username [الاسم]</code>\n"
        "• لتعيين الافتراضي: <code>/set_destination @username</code>"
    )

    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)
            return
        except Exception:
            pass
    await target_msg.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)


async def set_destination_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين بوت الاستلام الافتراضي"""
    sender_id = update.effective_user.id
    target_msg = update.effective_message
    if not is_bridge_admin(sender_id):
        await target_msg.reply_text("⛔ هذا الأمر مخصص لمالك البوت والمشرفين العامين فقط.", parse_mode="HTML")
        return

    if not context.args:
        await target_msg.reply_text("✍️ يرجى كتابة يوزرنيم البوت المستهدف:\nمثال: <code>/set_destination @MidasbuyHelp_bot</code>", parse_mode="HTML")
        return
    new_target = context.args[0].replace("@", "").strip()
    bridge_db.set_default_destination(new_target)
    await target_msg.reply_text(
        f"⭐ <b>تم تعيين بوت الاستلام الافتراضي بنجاح!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>البوت النشط:</b> @{new_target}\n"
        f"🔗 سيتم الآن تحويل كافة روابط الشحن تلقائياً إلى هذا البوت.",
        parse_mode="HTML"
    )


async def remove_bot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف بوت استلام من القائمة"""
    sender_id = update.effective_user.id
    target_msg = update.effective_message
    if not is_bridge_admin(sender_id):
        await target_msg.reply_text("⛔ هذا الأمر مخصص لمالك البوت والمشرفين العامين فقط.", parse_mode="HTML")
        return

    if not context.args:
        await target_msg.reply_text("⚠️ يرجى كتابة يوزرنيم البوت المراد حذفه:\nمثال: <code>/remove_bot @BotUsername</code>", parse_mode="HTML")
        return

    raw_user = context.args[0].replace("@", "").strip()
    bridge_db.remove_destination(raw_user)
    await target_msg.reply_text(f"🗑️ <b>تمت إزالة البوت @{raw_user} من قائمة بوتات الاستلام بنجاح.</b>", parse_mode="HTML")


def is_bridge_admin(user_id: int) -> bool:
    """التحقق مما إذا كان المستخدم مالكاً أو مشرفاً عاماً له صلاحية إدارة الأدمنز"""
    if user_id in [5620024477] or user_id in ADMIN_IDS:
        return True
    if BRIDGE_AVAILABLE:
        u = bridge_db.get_user(user_id)
        if u and u.get("is_active") and u.get("role") in ["OWNER", "SUPER_ADMIN"]:
            return True
    return False


async def allow_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة أو ترقية شخص كأدمن مصرح له بتحويل الروابط"""
    sender_id = update.effective_user.id
    target_msg = update.effective_message
    if not is_bridge_admin(sender_id):
        await target_msg.reply_text("⛔ هذا الأمر مخصص لمالك البوت والمشرفين العامين فقط.", parse_mode="HTML")
        return

    target_id = None
    target_username = None
    target_name = None
    role_arg = "ADMIN"

    # إذا تم الرد على رسالة مستخدم
    if update.message and update.message.reply_to_message and update.message.reply_to_message.from_user:
        u = update.message.reply_to_message.from_user
        target_id = u.id
        target_username = u.username
        target_name = u.first_name
        if context.args:
            role_arg = " ".join(context.args).strip()
    elif context.args:
        raw_id = context.args[0].replace("@", "").strip()
        if raw_id.isdigit():
            target_id = int(raw_id)
            if len(context.args) > 1:
                role_arg = " ".join(context.args[1:]).strip()
        else:
            await target_msg.reply_text(
                "⚠️ <b>يرجى كتابة الـ User ID المكوّن من أرقام:</b>\n"
                "مثال: <code>/add_admin 123456789 مشرف</code>\n"
                "أو: <code>/add_admin 123456789 مشرف عام</code>",
                parse_mode="HTML"
            )
            return

    if not target_id:
        await target_msg.reply_text(
            "✍️ <b>طريقة إضافة أو ترقية أدمن:</b>\n"
            "1. اكتب الأمر مع المعرف: <code>/add_admin 123456789 [الرتبة]</code>\n"
            "   (الرتب: <code>مشرف عام</code> | <code>مشرف</code> | <code>عضو مصرح</code>)\n"
            "2. أو قم بالرد (Reply) على رسالة الشخص واكتب: <code>/add_admin [الرتبة]</code>",
            parse_mode="HTML"
        )
        return

    final_role = normalize_role_input(role_arg)
    bridge_db.add_allowed_user(target_id, username=target_username, full_name=target_name, role=final_role)
    role_title = format_role_title(final_role)

    await target_msg.reply_text(
        f"✅ <b>تمت إضافة/ترقية الأدمن بنجاح!</b> 👑\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>الاسم:</b> {target_name or 'غير متوفر'}\n"
        f"🆔 <b>المعرف (ID):</b> <code>{target_id}</code>\n"
        f"🎖️ <b>الرتبة:</b> {role_title}\n\n"
        f"🔗 أصبح بإمكانه الآن إرسال روابط الشحن، وسيقوم البوت بتحويلها تلقائياً مع إبراز اسمه ورتبته.",
        parse_mode="HTML"
    )


async def set_role_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعديل رتبة أدمن أو مستخدم مصرح له"""
    sender_id = update.effective_user.id
    target_msg = update.effective_message
    if not is_bridge_admin(sender_id):
        await target_msg.reply_text("⛔ هذا الأمر مخصص لمالك البوت والمشرفين العامين فقط.", parse_mode="HTML")
        return

    target_id = None
    role_arg = ""

    if update.message and update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_id = update.message.reply_to_message.from_user.id
        if context.args:
            role_arg = " ".join(context.args).strip()
    elif context.args and len(context.args) >= 2:
        if context.args[0].isdigit():
            target_id = int(context.args[0])
            role_arg = " ".join(context.args[1:]).strip()

    if not target_id or not role_arg:
        await target_msg.reply_text(
            "✍️ <b>طريقة تعديل الرتبة:</b>\n"
            "• اكتب: <code>/set_role [User_ID] [الرتبة]</code>\n"
            "  (مثال: <code>/set_role 123456789 مشرف عام</code>)\n"
            "• أو قم بعمل Reply على رسالة الشخص مع: <code>/set_role [الرتبة]</code>",
            parse_mode="HTML"
        )
        return

    if target_id == 5620024477:
        await target_msg.reply_text("⚠️ لا يمكن تعديل رتبة مالك النظام الأساسي.", parse_mode="HTML")
        return

    final_role = normalize_role_input(role_arg)
    bridge_db.update_user_role(target_id, final_role)
    title = format_role_title(final_role)

    await target_msg.reply_text(
        f"🎖️ <b>تم تحديث الرتبة بنجاح!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>المعرف:</b> <code>{target_id}</code>\n"
        f"🎖️ <b>الرتبة الجديدة:</b> {title}",
        parse_mode="HTML"
    )


async def disallow_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إزالة شخص من قائمة الأدمن والمصرح لهم"""
    sender_id = update.effective_user.id
    target_msg = update.effective_message
    if not is_bridge_admin(sender_id):
        await target_msg.reply_text("⛔ هذا الأمر مخصص لمالك البوت والمشرفين العامين فقط.", parse_mode="HTML")
        return

    target_id = None
    if update.message and update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_id = update.message.reply_to_message.from_user.id
    elif context.args and context.args[0].isdigit():
        target_id = int(context.args[0])

    if not target_id:
        await target_msg.reply_text("⚠️ يرجى كتابة الـ User ID أو الرد على رسالة الشخص:\nمثال: <code>/disallow 123456789</code>", parse_mode="HTML")
        return

    if target_id == 5620024477:
        await target_msg.reply_text("⚠️ لا يمكن إزالة مالك البوت الأساسي.", parse_mode="HTML")
        return

    bridge_db.remove_allowed_user(target_id)
    await target_msg.reply_text(f"🚫 <b>تمت إزالة المستخدم</b> (ID: <code>{target_id}</code>) <b>من قائمة الأدمن والمصرح لهم.</b>", parse_mode="HTML")


async def allowed_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة طاقم الإدارة والأشخاص المصرح لهم بتحويل الروابط"""
    sender_id = update.effective_user.id
    target_msg = update.effective_message
    if not is_bridge_admin(sender_id):
        await target_msg.reply_text("⛔ هذا الأمر مخصص لمالك البوت والمشرفين العامين فقط.", parse_mode="HTML")
        return

    users = bridge_db.list_allowed_users()

    text = (
        "👥 <b>طاقم الإدارة والمصرح لهم بتحويل الروابط:</b> 👑\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    )
    buttons = []
    for idx, u in enumerate(users, 1):
        uname = f"(@{u['username']})" if u.get("username") else ""
        fname = u.get("full_name") or "مستخدم"
        role_badge = format_role_title(u.get("role", "ADMIN"))
        text += f"{idx}. <b>{fname}</b> {uname}\n   └ 🆔 <code>{u['user_id']}</code> | {role_badge}\n\n"
        if u["user_id"] != 5620024477:
            buttons.append([
                InlineKeyboardButton(f"✏️ رتبة {fname[:10]}", callback_data=f"role_menu_{u['user_id']}"),
                InlineKeyboardButton(f"❌ إزالة", callback_data=f"rm_allowed_{u['user_id']}")
            ])

    text += (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "➕ <b>لإضافة أو ترقية أدمن:</b>\n"
        "• <code>/add_admin [User_ID] [الرتبة]</code>\n"
        "• أو قم بعمل Reply على رسالته مع <code>/add_admin</code>\n"
        "• لتعديل الرتبة: <code>/set_role [User_ID] [الرتبة]</code>"
    )

    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)
            return
        except Exception:
            pass
    await target_msg.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)


async def handle_bridge_incoming_links(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """معالجة الروابط الواردة وإرسالها عبر حساب تيليجرام الشخصي بالتتابع مع إظهار المرسل ورتبته"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    user_name = update.effective_user.full_name or update.effective_user.first_name or "مستخدم"
    username_str = f"(@{update.effective_user.username})" if update.effective_user.username else ""
    sender_display = f"<b>{user_name}</b> {username_str}".strip()

    # 1. التحقق من صلاحية المستخدم (Whitelist Authorization Check)
    if not bridge_db.is_user_allowed(user_id):
        await update.message.reply_text(
            f"⛔ <b>عذراً، هذا البوت مخصص للأدمن والمصرح لهم فقط!</b> 🛡️\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>الاسم:</b> {sender_display}\n"
            f"🆔 <b>معرف حسابك (User ID):</b> <code>{user_id}</code>\n"
            f"❌ <b>الرتبة:</b> غير مصرح (Unauthorized)\n\n"
            f"<i>يرجى إرسال الـ User ID الخاص بك إلى مالك البوت لترقيتك أو إضافتك كأدمن.</i>",
            parse_mode="HTML"
        )
        return

    forwarding_enabled = bridge_db.get_setting("forwarding_enabled", "true").lower() == "true"
    if not forwarding_enabled:
        await update.message.reply_text("⚠️ <b>نظام تحويل الروابط متوقف حالياً.</b>\nيمكنك تفعيله بالأمر <code>/forward_on</code>.", parse_mode="HTML")
        return

    links = extract_links(text)
    if not links:
        return

    user_record = bridge_db.get_user(user_id) or {}
    role = user_record.get("role") or ("OWNER" if user_id == 5620024477 else "ADMIN")
    role_title = format_role_title(role)

    for link in links:
        if deduplicator.is_duplicate(link, user_id):
            await update.message.reply_text(
                f"⚠️ <b>تم تجاهل تكرار الرابط:</b>\n<code>{link}</code>\n<i>تم إرسال هذا الرابط مؤخراً لتجنب الازدواجية.</i>",
                parse_mode="HTML"
            )
            continue

        txn_id = generate_transaction_id()

        # فحص هل تم تحديد بوت استلام معين في الرسالة المصاحبة للرابط
        custom_bot = None
        for word in text.split():
            clean_word = word.replace("@", "").strip().lower()
            if clean_word in [u.lower() for u in bridge_db.get_active_destination_usernames()]:
                custom_bot = word.replace("@", "").strip()
                break
        dest_bot = custom_bot or bridge_db.get_setting("default_destination", "MidasbuyHelp_bot")

        bridge_db.create_transaction({
            "transaction_id": txn_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "original_link": link,
            "raw_message_text": text,
            "destination_bot": dest_bot,
            "status": TransactionStatus.PENDING.value
        })

        await update.message.reply_text(
            f"🔄 <b>تم استلام رابط شحن جديد!</b> 👑\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>المرسل:</b> {sender_display}\n"
            f"🎖️ <b>الرتبة:</b> {role_title}\n"
            f"🆔 <b>معرف الحساب:</b> <code>{user_id}</code>\n"
            f"🔗 <b>الرابط:</b> <code>{link}</code>\n"
            f"🔖 <b>رقم العملية:</b> <code>{txn_id}</code>\n"
            f"🎯 <b>الوجهة:</b> @{dest_bot}\n"
            f"⚡ <b>الوسيط:</b> حساب تيليجرام الشخصي (@VIPSTORE1S)\n\n"
            f"⏳ <i>جارٍ التحويل للبوت وجلب الرد التفاعلي...</i>",
            parse_mode="HTML"
        )

        await queue_manager.enqueue_link({
            "transaction_id": txn_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "original_link": link,
            "raw_message_text": text,
            "destination_bot": dest_bot,
            "sender_name": user_name,
            "sender_username": update.effective_user.username or "",
            "sender_role": role,
            "sender_role_title": role_title,
        })


async def handle_bridge_button_click(query, context, data_str: str):
    """الضغط العكسي على زر تفاعلي في البوت المستهدف عبر حساب تيليجرام الشخصي"""
    parts = data_str.split("_")
    if len(parts) >= 4:
        txn_id = parts[1]
        row = int(parts[2])
        col = int(parts[3])
        await query.answer("⏳ جاري تنفيذ الضغط على الزر في البوت المستهدف...")
        success = await queue_manager.trigger_button_click(
            txn_id=txn_id,
            row=row,
            col=col,
            user_id=query.from_user.id
        )
        if not success:
            await query.answer("⚠️ تعذر تنفيذ الضغط على الزر في البوت المستهدف.", show_alert=True)
    else:
        await query.answer()



# =============================================================================
#  المعالج الرئيسي للرسائل
# =============================================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة رسائل الطلبات وإدخال البيانات الناقصة والتفاعل مع الأزرار"""
    text = update.message.text.strip()
    session = context.user_data.get("session")

    # 0. فحص أزرار لوحة المفاتيح السفلية المباشرة
    if text in ["📊 التقرير المالي العام", "التقرير المالي"]:
        await report_command(update, context)
        return
    elif text in ["📦 أحدث الطلبات", "الطلبات"]:
        await orders_command(update, context)
        return
    elif text in ["📑 استخراج فاتورة عميل", "استخراج فاتورة"]:
        context.user_data["awaiting_invoice_number"] = True
        await update.message.reply_text(
            "✍️ <b>يرجى إرسال رقم الطلب المطلوب استخراج فاتورته الآن:</b>\n"
            "مثال: <code>VIP-A79G7U</code>",
            parse_mode="HTML"
        )
        return
    elif text in ["📥 تصدير سجل Excel", "تصدير Excel"]:
        await export_command(update, context)
        return
    elif text in ["📌 تثبيت التقرير بالجروب", "تثبيت التقرير"]:
        await pinreport_command(update, context)
        return
    elif text in ["ℹ️ دليل واستخدام النظام", "دليل النظام", "المساعدة"]:
        await help_command(update, context)
        return
    elif text in ["⚙️ لوحة التحكم", "لوحة الأزرار", "/menu"]:
        await menu_command(update, context)
        return
    elif text in ["⚡ وسيط روابط Midasbuy", "وسيط الروابط", "حالة وسيط الروابط"]:
        await forward_status_command(update, context)
        return

    # فحص ما إذا كانت الرسالة تحتوي على رابط شحن (Midasbuy / Generic Links) لتحويله فوراً
    if BRIDGE_AVAILABLE and has_links(text):
        await handle_bridge_incoming_links(update, context, text)
        return

    # إذا كان المستخدم في وضع إدخال رقم الطلب لاستخراج فاتورة العميل
    if context.user_data.get("awaiting_invoice_number"):
        context.user_data["awaiting_invoice_number"] = False
        await send_invoice_by_order(update.effective_chat.id, context.bot, text.strip())
        return

    # 1. إذا كان المستخدم في وضع إدخال حقل محدد (Awaiting a specific field)
    if session and session.get("awaiting_field"):
        field_key = session["awaiting_field"]
        session["awaiting_field"] = None

        order_data = session["order_data"]
        label_map = {
            "order_number": "رقم الطلب",
            "customer_name": "اسم العميل",
            "account_name": "اسم الحساب",
            "player_id": "ID الحساب",
            "quantity": "الكمية",
            "cost": "التكلفة",
            "profit": "الأرباح",
            "losses": "الخسائر",
            "total_amount": "الإجمالي",
            "product_name": "الباقة",
            "date": "التاريخ",
        }

        # تعيين القيمة حسب نوع الحقل
        if field_key in ["quantity", "cost", "profit", "losses", "total_amount"]:
            try:
                num_val = float(re.sub(r'[^\d.\-]', '', text))
                order_data[field_key] = num_val
                if field_key == "quantity" and order_data.get("items"):
                    order_data["items"][0]["quantity"] = num_val
            except ValueError:
                pass
        else:
            order_data[field_key] = text

        # تحديث صافي الربح
        rev = float(order_data.get("total_amount", 0.0))
        cost = float(order_data.get("cost", 0.0))
        losses = float(order_data.get("losses", 0.0))
        if order_data.get("profit"):
            order_data["net_profit"] = order_data["profit"]
        else:
            order_data["net_profit"] = rev - cost - losses

        # إزالة الحقل من قائمة الناقصة
        session["missing_fields"] = [m for m in session["missing_fields"] if m["key"] != field_key]

        lbl = label_map.get(field_key, field_key)
        await update.message.reply_text(f"✅ تم إضافة <b>{lbl}</b>: <code>{text}</code>", parse_mode="HTML")

        # إذا لم يعد هناك حقول ناقصة، ننتقل مباشرة للمراجعة
        if not session["missing_fields"]:
            msg, reply_markup = format_review_summary(order_data)
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=reply_markup)
        else:
            msg, reply_markup = format_missing_fields_menu(session)
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=reply_markup)
        return

    # 2. إذا كان المستخدم يرسل بيانات نصية عامة لتحديث الطلب الحالي قيد الانتظار
    if session and "order_data" in session and ("الطلب" in text or "العميل" in text or "الحساب" in text or "ID" in text or "الكمية" in text):
        order_data = session["order_data"]
        updated_fields = update_order_with_text(order_data, text)
        if updated_fields:
            # إزالة الحقول المحدثة من قائمة الناقصة
            key_map = {"رقم الطلب": "order_number", "اسم العميل": "customer_name", "الهاتف": "customer_phone", "اسم الحساب": "account_name", "ID الحساب": "player_id", "الكمية": "quantity"}
            keys_to_remove = [key_map[uf] for uf in updated_fields if uf in key_map]
            session["missing_fields"] = [m for m in session["missing_fields"] if m["key"] not in keys_to_remove]

            await update.message.reply_text(f"✅ تم تحديث: {', '.join(updated_fields)} بنجاح!", parse_mode="HTML")

            if not session["missing_fields"]:
                msg, reply_markup = format_review_summary(order_data)
                await update.message.reply_text(msg, parse_mode="HTML", reply_markup=reply_markup)
            else:
                msg, reply_markup = format_missing_fields_menu(session)
                await update.message.reply_text(msg, parse_mode="HTML", reply_markup=reply_markup)
            return

    # 3. استقبال وتحليل رسالة طلب جديدة
    chat = update.effective_chat
    is_group = chat and chat.type in ["group", "supergroup"]

    # فحص صارم ودقيق: هل الرسالة رسالة طلب أو شحن حقيقية؟
    if not is_order_message(text):
        # في الجروبات: تجاهل تام لأي دردشة أو رسائل عادية
        if is_group:
            return

        # في المحادثات الخاصة: نرد فقط إذا كانت تحية أو استفسار دون إنشاء فاتورة
        greetings = ["السلام", "مرحبا", "اهلا", "أهلا", "صباح", "مساء", "ازيك", "عامل ايه", "هلا", "hi", "hello", "سلام"]
        if any(g in text.lower() for g in greetings):
            await update.message.reply_text(
                "👑 <b>أهلاً بك في VIP STORE – GAMING SERVICES!</b>\n\n"
                "لإنشاء فاتورة جديدة، يرجى إرسال بيانات الطلب أو رسالة تأكيد الشحن.\n"
                "⚠️ <i>ملاحظة: البوت مبرمج ليتعرف فقط على رسائل الطلبات والشحن لتفادي تحويل أي رسائل عادية أو دردشة إلى فواتير.</i>\n\n"
                "📋 <b>مثال لرسالة طلب معتمدة:</b>\n"
                "<code>📋 رقم الطلب: VIP-A79G7U\n"
                "🎁 الباقة: 325 BONUS\n"
                "💰 التكلفة: 250 جنيه\n"
                "📈 الأرباح: +20 جنيه\n"
                "💵 الإجمالي: 270 جنيه</code>",
                parse_mode="HTML"
            )
        return

    # تم التأكد من أن الرسالة عبارة عن طلب شحن حقيقي:
    inspection = inspect_missing_data(text)
    order_data = inspection["order_data"]
    order_num = order_data.get("order_number") or ""

    # قاعدة صارمة: منع تكرار احتساب أي طلب موجود بالفعل
    if order_num and db.order_exists(order_num):
        existing = db.get_invoice_by_order(order_num)
        await update.message.reply_text(
            f"⚠️ <b>تنبيه: تم رفض الطلب لمنع التكرار!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"رقم الطلب <code>#{order_num}</code> مسجل ومحتسب مسبقاً في قاعدة البيانات!\n"
            f"📅 <b>تاريخ التسجيل:</b> {existing.get('date', '—')}\n"
            f"👤 <b>العميل:</b> {existing.get('customer_name', '—')}\n"
            f"💵 <b>الإجمالي:</b> {existing.get('total_amount', 0.0):,.2f} ج.م\n"
            f"💰 <b>صافي الربح السابق:</b> {existing.get('net_profit', 0.0):,.2f} ج.م",
            parse_mode="HTML"
        )
        return

    # حفظ الجلسة في user_data
    context.user_data["session"] = inspection

    # إذا لم تكن هناك بيانات ناقصة على الإطلاق، ننتقل مباشرة للمراجعة والاعتماد
    if not inspection["missing_fields"]:
        msg, reply_markup = format_review_summary(order_data)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=reply_markup)
        return

    # عرض فحص البيانات الناقصة وسؤال المستخدم
    msg, reply_markup = format_missing_data_prompt(inspection)
    await update.message.reply_text(msg, parse_mode="HTML", reply_markup=reply_markup)


# =============================================================================
#  معالجة الأزرار التفاعلية
# =============================================================================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أزرار إضافة البيانات، التخطي، والاعتماد"""
    query = update.callback_query
    await query.answer()
    data = query.data
    session = context.user_data.get("session")

    # إلغاء الطلب
    if data == "btn_cancel_order":
        if "session" in context.user_data:
            del context.user_data["session"]
        await query.edit_message_text("❌ تم إلغاء العملية.", parse_mode="HTML")
        return

    # أزرار وسيط الروابط التفاعلية (Inline Buttons from Target Bot)
    if data.startswith("brg_"):
        await handle_bridge_button_click(query, context, data)
        return

    if data == "cmd_bridge_status":
        await forward_status_command(update, context)
        return

    if data == "cmd_bridge_test":
        await forward_test_command(update, context)
        return

    if data == "cmd_allowed_users":
        if not is_bridge_admin(query.from_user.id):
            await query.answer("⛔ هذه الميزة مخصصة للمالك والمشرفين العامين فقط.", show_alert=True)
            return
        await allowed_users_command(update, context)
        return

    if data == "cmd_bots_list":
        if not is_bridge_admin(query.from_user.id):
            await query.answer("⛔ هذه الميزة مخصصة للمشرفين فقط.", show_alert=True)
            return
        await bots_command(update, context)
        return

    if data == "cmd_prompt_add_bot":
        await query.answer()
        await query.message.reply_text(
            "➕ <b>لإضافة بوت استلام جديد:</b>\n"
            "اكتب الأمر متبوعاً بيوزرنيم البوت:\n"
            "<code>/add_bot @BotUsername [اسم البوت]</code>\n\n"
            "📌 <b>مثال:</b>\n"
            "<code>/add_bot @MidasbuyHelp_bot بوت الشحن الرئيسي</code>",
            parse_mode="HTML"
        )
        return

    if data.startswith("set_def_bot_"):
        if not is_bridge_admin(query.from_user.id):
            await query.answer("⛔ لا تملك صلاحية تغيير البوت الافتراضي.", show_alert=True)
            return
        bot_user = data.replace("set_def_bot_", "")
        bridge_db.set_default_destination(bot_user)
        await query.answer(f"تم تفعيل @{bot_user} كبوت افتراضي!", show_alert=True)
        await bots_command(update, context)
        return

    if data.startswith("test_bot_"):
        bot_user = data.replace("test_bot_", "")
        await query.answer("⏳ جاري فحص البوت...", show_alert=False)
        res = await telethon_manager.check_bot_entity(bot_user)
        if res.get("success"):
            await query.message.reply_text(
                f"✅ <b>فحص اتصال البوت @{bot_user}:</b>\n"
                f"• الاسم: <b>{res.get('title')}</b>\n"
                f"• المعرف (ID): <code>{res.get('id')}</code>\n"
                f"• الحالة: 🟢 متصل وجاهز للاستقبال",
                parse_mode="HTML"
            )
        else:
            await query.message.reply_text(f"❌ <b>فشل فحص البوت @{bot_user}:</b> <code>{res.get('error')}</code>", parse_mode="HTML")
        return

    if data.startswith("rm_bot_"):
        if not is_bridge_admin(query.from_user.id):
            await query.answer("⛔ لا تملك صلاحية حذف البوتات.", show_alert=True)
            return
        bot_user = data.replace("rm_bot_", "")
        bridge_db.remove_destination(bot_user)
        await query.answer(f"تمت إزالة @{bot_user} بنجاح!", show_alert=True)
        await bots_command(update, context)
        return

    if data.startswith("role_menu_"):
        if not is_bridge_admin(query.from_user.id):
            await query.answer("⛔ لا تملك صلاحية تعديل الرتب.", show_alert=True)
            return
        uid = int(data.replace("role_menu_", ""))
        user_info = bridge_db.get_user(uid) or {}
        uname = user_info.get("full_name") or str(uid)
        curr_role = format_role_title(user_info.get("role", "ADMIN"))

        role_buttons = [
            [
                InlineKeyboardButton("🛡️ مشرف عام", callback_data=f"set_role_{uid}_SUPER_ADMIN"),
                InlineKeyboardButton("⚡ مشرف", callback_data=f"set_role_{uid}_ADMIN"),
            ],
            [
                InlineKeyboardButton("⭐ عضو مصرح", callback_data=f"set_role_{uid}_MEMBER"),
            ],
            [
                InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="cmd_allowed_users"),
            ]
        ]
        await query.edit_message_text(
            f"🎖️ <b>تحديد رتبة المستخدم:</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>الاسم:</b> {uname}\n"
            f"🆔 <b>المعرف:</b> <code>{uid}</code>\n"
            f"📌 <b>الرتبة الحالية:</b> {curr_role}\n\n"
            f"👇 <i>اختر الرتبة الجديدة من الأزرار أدناه:</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(role_buttons)
        )
        return

    if data.startswith("set_role_"):
        if not is_bridge_admin(query.from_user.id):
            await query.answer("⛔ لا تملك صلاحية تعديل الرتب.", show_alert=True)
            return
        parts = data.split("_")
        uid = int(parts[2])
        new_role = "_".join(parts[3:])
        bridge_db.update_user_role(uid, new_role)
        title = format_role_title(new_role)
        await query.answer(f"تم تغيير الرتبة إلى: {title}", show_alert=True)
        await allowed_users_command(update, context)
        return

    if data.startswith("rm_allowed_"):
        if not is_bridge_admin(query.from_user.id):
            await query.answer("⛔ لا تملك صلاحية تعديل القائمة.", show_alert=True)
            return
        uid = int(data.replace("rm_allowed_", ""))
        if uid == 5620024477:
            await query.answer("⚠️ لا يمكن إزالة مالك البوت الأساسي.", show_alert=True)
            return
        bridge_db.remove_allowed_user(uid)
        await query.answer("تمت إزالة الأدمن/المستخدم بنجاح!", show_alert=True)
        await allowed_users_command(update, context)
        return

    # --- أزرار لوحة التحكم التفاعلية السريعة (لا تتطلب جلسة طلب) ---
    if data == "cmd_report":
        metrics = db.get_cumulative_metrics()
        report_text = format_cumulative_report_message(metrics)
        await query.message.reply_text(report_text, parse_mode="HTML")
        return

    if data == "cmd_orders":
        await send_recent_orders(query.message)
        return

    if data == "cmd_get_invoice":
        context.user_data["awaiting_invoice_number"] = True
        await query.message.reply_text(
            "✍️ <b>يرجى إرسال رقم الطلب المطلوب استخراج فاتورته الآن:</b>\n"
            "مثال: <code>VIP-A79G7U</code>",
            parse_mode="HTML"
        )
        return

    if data == "cmd_export":
        await perform_export(query.message)
        return

    if data == "cmd_pinreport":
        chat_id = update.effective_chat.id
        metrics = db.get_cumulative_metrics()
        report_text = format_cumulative_report_message(metrics)
        sent_msg = await query.message.reply_text(report_text, parse_mode="HTML")
        try:
            await context.bot.pin_chat_message(
                chat_id=chat_id,
                message_id=sent_msg.message_id,
                disable_notification=True
            )
            db.set_setting("pinned_report_message_id", str(sent_msg.message_id))
            db.set_setting("pinned_report_chat_id", str(chat_id))
            await query.message.reply_text("📌 <b>تم تثبيت رسالة التقرير بنجاح!</b>", parse_mode="HTML")
        except Exception as e:
            await query.message.reply_text(f"⚠️ تعذر التثبيت: {e}\n(تأكد من إعطاء البوت صلاحية التثبيت).", parse_mode="HTML")
        return

    if data == "cmd_help":
        await send_help_guide(query.message)
        return

    if not session or "order_data" not in session:
        await query.edit_message_text("⚠️ انتهت صلاحية الجلسة، يرجى إرسال الطلب مرة أخرى.", parse_mode="HTML")
        return

    # 1. زر إضافة بيانات ناقصة
    if data == "btn_add_missing":
        msg, reply_markup = format_missing_fields_menu(session)
        await query.edit_message_text(msg, parse_mode="HTML", reply_markup=reply_markup)
        return

    # 2. زر اختيار حقل محدد للإدخال
    if data.startswith("field_"):
        field_key = data.replace("field_", "")
        session["awaiting_field"] = field_key

        label_map = {
            "customer_name": "اسم العميل",
            "account_name": "اسم الحساب داخل اللعبة",
            "player_id": "ID الحساب (Player ID)",
            "quantity": "الكمية",
            "cost": "التكلفة (سعر الشراء)",
            "profit": "الأرباح",
            "losses": "الخسائر",
            "total_amount": "الإجمالي (سعر البيع)",
            "product_name": "اسم الباقة أو المنتج",
            "date": "التاريخ",
        }
        lbl = label_map.get(field_key, field_key)

        back_buttons = [[InlineKeyboardButton("🔙 رجوع لقائمة الحقول", callback_data="btn_add_missing")]]
        await query.edit_message_text(
            f"✍️ يرجى إرسال <b>{lbl}</b> الآن عبر رسالة نصية:\n(أو اضغط رجوع إذا كنت تفضل التخطي)",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(back_buttons)
        )
        return

    # 3. زر تخطي واستكمال الفاتورة بالبيانات المتوفرة
    if data == "btn_skip_missing":
        session["awaiting_field"] = None
        order_data = session["order_data"]
        if not order_data.get("order_number"):
            order_data["order_number"] = f"VIP-{datetime.now().strftime('%m%d%H%M')}"
        msg, reply_markup = format_review_summary(order_data)
        await query.edit_message_text(msg, parse_mode="HTML", reply_markup=reply_markup)
        return

    # 4. زر اعتماد وتسجيل الفاتورة نهائياً
    if data == "btn_confirm_approve":
        order_data = session["order_data"]
        order_num = order_data.get("order_number") or ""
        if not order_num:
            order_num = f"VIP-{datetime.now().strftime('%m%d%H%M')}"
            order_data["order_number"] = order_num

        # التحقق من عدم التكرار مرة أخيرة قبل الحفظ
        if db.order_exists(order_num):
            await query.edit_message_text("⚠️ هذا الطلب مسجل مسبقاً بالفعل لمنع التكرار!", parse_mode="HTML")
            return

        order_data["status"] = "published"

        # --- القسم الأول: إنشاء وتجهيز فاتورة العميل الرسمية (Image + PDF) ---
        invoice = Invoice.from_dict(order_data)
        img_bytes = render_invoice_image(invoice)
        pdf_bytes = render_invoice_pdf(invoice)

        # حفظ الملفات محلياً
        invoices_dir = OUTPUT_DIR / "invoices"
        invoices_dir.mkdir(parents=True, exist_ok=True)
        clean_file_id = re.sub(r'[^\w\-]', '_', order_num)
        pdf_path = invoices_dir / f"{clean_file_id}.pdf"
        img_path = invoices_dir / f"{clean_file_id}.png"

        try:
            pdf_path.write_bytes(pdf_bytes)
            img_path.write_bytes(img_bytes)
            order_data["pdf_path"] = str(pdf_path)
            order_data["image_path"] = str(img_path)
        except Exception as e:
            logger.warning(f"تعذر حفظ الملفات على القرص: {e}")

        # حفظ الطلب في قاعدة البيانات والمزامنة مع Supabase
        db.save_invoice(order_data)

        # مسح الجلسة
        del context.user_data["session"]

        # إرسال فاتورة العميل (صورة + PDF) للمستخدم/الأدمن
        chat_id = update.effective_chat.id
        cust_name = order_data.get("customer_name") or "—"
        acc_name = order_data.get("account_name") or "—"
        player_id = order_data.get("player_id") or "—"
        prod_name = order_data.get("product_name") or "شحن ألعاب"
        tot_amount = float(order_data.get("total_amount", 0.0))

        caption = (
            f"📄 <b>فاتورة العميل الرسمية - طلب #{order_num}</b> 👑\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>اسم العميل:</b> {cust_name}\n"
            f"🎮 <b>اسم الحساب:</b> <code>{acc_name}</code>\n"
            f"🆔 <b>ID الحساب:</b> <code>{player_id}</code>\n"
            f"📦 <b>الباقة:</b> {prod_name}\n"
            f"💵 <b>المبلغ المطلوب:</b> {tot_amount:,.2f} ج.م\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ <i>تم إنشاء الصورة وملف الـ PDF بجودة فائقة للإرسال للعميل مباشرة.</i>"
        )

        try:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=io.BytesIO(img_bytes),
                caption=caption,
                parse_mode="HTML"
            )
            await context.bot.send_document(
                chat_id=chat_id,
                document=io.BytesIO(pdf_bytes),
                filename=f"{clean_file_id}.pdf",
                caption=f"📎 <b>ملف PDF الرسمي للطلب:</b> <code>{clean_file_id}.pdf</code>",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"خطأ في إرسال فاتورة العميل: {e}")

        # --- القسم الثاني: تنفيذ بروتوكول الرسالتين في جروب VIP STORE ADMINS ---
        target_group = get_target_group_id(update)
        await execute_two_messages_protocol(context.bot, target_group, order_data)

        success_msg = (
            f"🎉 <b>تم اعتماد وتسجيل الطلب #{order_num} بنجاح!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>القسم الأول (فاتورة العميل):</b> تم إرسال الصورة وملف الـ PDF أعلاه للإرسال للعميل فوراً.\n"
            f"👥 <b>القسم الثاني (جروب الإدارة):</b>\n"
            f"  1️⃣ أُرسلت رسالة تفاصيل الطلب والحساب المالي للجروب.\n"
            f"  2️⃣ تم تحديث وتثبيت رسالة التقرير المالي التراكمي بالأرباح الجديدة.\n"
            f"💾 <b>قاعدة البيانات:</b> تم الحفظ الدائم وتثبيت الأرباح التراكمية ومنع تكرار الطلب."
        )

        await query.edit_message_text(success_msg, parse_mode="HTML")
        return


# =============================================================================
#  تشغيل التطبيق
# =============================================================================

def build_application() -> Application:
    """بناء تطبيق البوت الموحد مع وسيط الروابط"""
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(on_bridge_startup)
        .post_shutdown(on_bridge_shutdown)
        .build()
    )

    # الأوامر الأساسية
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("buttons", menu_command))
    app.add_handler(CommandHandler("invoice", invoice_command))
    app.add_handler(CommandHandler("getinvoice", invoice_command))
    app.add_handler(CommandHandler("pdf", invoice_command))
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CommandHandler("recent", orders_command))
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("stats", report_command))
    app.add_handler(CommandHandler("financials", report_command))
    app.add_handler(CommandHandler("pinreport", pinreport_command))
    app.add_handler(CommandHandler("setgroup", setgroup_command))
    app.add_handler(CommandHandler("cancel", cancel_command))

    # أوامر وسيط الروابط وإدارة الأدمنز وبوتات الاستلام (VIP STORE LINK BRIDGE)
    app.add_handler(CommandHandler("forward_status", forward_status_command))
    app.add_handler(CommandHandler("forward_test", forward_test_command))
    app.add_handler(CommandHandler("forward_on", forward_on_command))
    app.add_handler(CommandHandler("forward_off", forward_off_command))
    app.add_handler(CommandHandler("add_bot", add_bot_command))
    app.add_handler(CommandHandler("add_destination", add_bot_command))
    app.add_handler(CommandHandler("bots", bots_command))
    app.add_handler(CommandHandler("destinations", bots_command))
    app.add_handler(CommandHandler("remove_bot", remove_bot_command))
    app.add_handler(CommandHandler("delete_bot", remove_bot_command))
    app.add_handler(CommandHandler("set_default_bot", set_destination_command))
    app.add_handler(CommandHandler("set_destination", set_destination_command))
    app.add_handler(CommandHandler("add_admin", allow_user_command))
    app.add_handler(CommandHandler("allow", allow_user_command))
    app.add_handler(CommandHandler("add_user", allow_user_command))
    app.add_handler(CommandHandler("set_role", set_role_command))
    app.add_handler(CommandHandler("setrole", set_role_command))
    app.add_handler(CommandHandler("disallow", disallow_user_command))
    app.add_handler(CommandHandler("remove_admin", disallow_user_command))
    app.add_handler(CommandHandler("remove_user", disallow_user_command))
    app.add_handler(CommandHandler("admins", allowed_users_command))
    app.add_handler(CommandHandler("allowed_users", allowed_users_command))
    app.add_handler(CommandHandler("whitelist", allowed_users_command))

    # الأزرار التفاعلية
    app.add_handler(CallbackQueryHandler(handle_callback))

    # معالج الرسائل النصية العام
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app


def start_health_server():
    """تشغيل خادم ويب خفيف للاستجابة لفحص Render والمنصات السحابية (Health Check)"""
    import os
    import threading
    port_str = os.environ.get("PORT", "7860")
    try:
        port = int(port_str)
    except ValueError:
        port = 7860

    def _serve():
        try:
            from http.server import HTTPServer, BaseHTTPRequestHandler
            class HealthHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"VIP STORE BOT 24/7 ONLINE")
                def log_message(self, *args):
                    pass
            server = HTTPServer(("0.0.0.0", port), HealthHandler)
            logger.info(f"خادم فحص الحالة السحابي يعمل على المنفذ: {port}")
            server.serve_forever()
        except Exception as e:
            logger.info(f"ملاحظة فحص الحالة: {e}")

    t = threading.Thread(target=_serve, daemon=True)
    t.start()


def main():
    """نقطة تشغيل البوت"""
    logger.info("جاري تشغيل VIP STORE – Smart Missing Data Assistant...")
    start_health_server()
    app = build_application()
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
