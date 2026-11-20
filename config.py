"""
config.py - إعدادات وثوابت البوت
Configuration and constants for the Invoice Telegram Bot
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# --- المسارات ---
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "templates"
USER_DATA_DIR = BASE_DIR / "user_data"
OUTPUT_DIR = BASE_DIR / "output"
ASSETS_DIR = BASE_DIR / "assets"
LOGO_PATH = ASSETS_DIR / "logo.jpg"
INVOICE_TEMPLATE_PATH = ASSETS_DIR / "invoice_template.jpg"
HEADER_PATH = ASSETS_DIR / "template_header.png"
FOOTER_PATH = ASSETS_DIR / "template_footer.png"
DB_PATH = DATA_DIR / "vip_store.db"

for d in (DATA_DIR, TEMPLATES_DIR, USER_DATA_DIR, OUTPUT_DIR, ASSETS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# تحميل متغيرات البيئة
load_dotenv(BASE_DIR / ".env")
load_dotenv()

# --- إعدادات البوت والخدمات ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
VIP_ADMINS_GROUP_ID = os.getenv("VIP_ADMINS_GROUP_ID", "")

# --- إعدادات القوالب ---
DEFAULT_TEMPLATES_FILE = TEMPLATES_DIR / "default_templates.json"

# --- إعدادات PDF ---
# مسار خط عربي (يمكن تغييره حسب النظام)
ARABIC_FONT_PATH = os.getenv("ARABIC_FONT_PATH", "")
# إذا لم يتم تحديد خط، نحاول البحث عن خطوط شائعة
DEFAULT_FONT_PATHS = [
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/System/Library/Fonts/Arial.ttf",
]

def get_arabic_font_path() -> str:
    """البحث عن مسار خط يدعم العربية"""
    if ARABIC_FONT_PATH and Path(ARABIC_FONT_PATH).exists():
        return ARABIC_FONT_PATH
    for font_path in DEFAULT_FONT_PATHS:
        if Path(font_path).exists():
            return font_path
    # في حالة عدم وجود أي خط، نعود للخط الافتراضي
    return ""

# --- إعدادات الصور ---
IMAGE_WIDTH = 800
IMAGE_HEIGHT = 1100
IMAGE_BG_COLOR = "#FFFFFF"
IMAGE_TEXT_COLOR = "#1a1a2e"
IMAGE_ACCENT_COLOR = "#0f3460"
IMAGE_HEADER_COLOR = "#16213e"

# --- نسبة الضريبة الافتراضية ---
DEFAULT_TAX_RATE = 0.15  # 15% ضريبة القيمة المضافة

# --- حالات المحادثة (Conversation States) ---
# حالات إنشاء الفاتورة
(
    INV_ORDER_NUMBER,
    INV_CUSTOMER_NAME,
    INV_CUSTOMER_PHONE,
    INV_PRODUCT_NAME,
    INV_PRODUCT_QTY,
    INV_PRODUCT_PRICE,
    INV_MORE_PRODUCTS,
    INV_TAX,
    INV_NOTES,
    INV_EXPORT_FORMAT,
) = range(10)

# حالات إنشاء عرض السعر
(
    QUOTE_CUSTOMER_NAME,
    QUOTE_CUSTOMER_PHONE,
    QUOTE_PRODUCT_NAME,
    QUOTE_PRODUCT_QTY,
    QUOTE_PRODUCT_PRICE,
    QUOTE_MORE_PRODUCTS,
    QUOTE_VALIDITY_DAYS,
    QUOTE_TERMS,
    QUOTE_NOTES,
    QUOTE_EXPORT_FORMAT,
) = range(10, 20)

# حالات إنشاء الإيصال
(
    RECEIPT_CUSTOMER_NAME,
    RECEIPT_AMOUNT,
    RECEIPT_PAYMENT_METHOD,
    RECEIPT_DESCRIPTION,
    RECEIPT_NOTES,
    RECEIPT_EXPORT_FORMAT,
) = range(20, 26)

# حالات إدارة القوالب
(
    TPL_ACTION,
    TPL_NAME,
    TPL_FIELD_NAME,
    TPL_FIELD_TYPE,
    TPL_MORE_FIELDS,
    TPL_CONFIRM,
) = range(30, 36)

# --- تكامل إعدادات وسيط الروابط (VIP STORE LINK BRIDGE) ---
BRIDGE_BASE_DIR = Path("C:/Users/MOAZ AMR/.gemini/antigravity/scratch/vip-store-link-bridge")
BRIDGE_DATA_DIR = BRIDGE_BASE_DIR / "data"
SESSIONS_DIR = BRIDGE_DATA_DIR / "sessions"
MEDIA_DIR = BRIDGE_DATA_DIR / "media"
LOGS_DIR = BRIDGE_DATA_DIR / "logs"
BRIDGE_DB_PATH = BRIDGE_DATA_DIR / "vip_store_bridge.db"

for _d in (SESSIONS_DIR, MEDIA_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

load_dotenv(BRIDGE_BASE_DIR / ".env")

PRIMARY_BOT_TOKEN = os.getenv("PRIMARY_BOT_TOKEN", BOT_TOKEN)
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(i.strip()) for i in ADMIN_IDS_RAW.split(",") if i.strip().isdigit()]

TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "34993665")) if os.getenv("TELEGRAM_API_ID", "34993665").isdigit() else 34993665
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "b5d9130dad484e35b55bded61e6b0771")
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "+201062318668")
SESSION_STRING = os.getenv("SESSION_STRING", "")

DEFAULT_DESTINATION_BOT = os.getenv("DEFAULT_DESTINATION_BOT", "MidasbuyHelp_bot").replace("@", "")
DEFAULT_REPLY_TIMEOUT_SECONDS = int(os.getenv("DEFAULT_REPLY_TIMEOUT_SECONDS", "60"))
QUEUE_SETTLE_SECONDS = float(os.getenv("QUEUE_SETTLE_SECONDS", "3.0"))
MAX_CONCURRENT_TRANSACTIONS = 1
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8088"))


# --- الرسائل العربية ---
MESSAGES = {
    "welcome": (
        "🧾 <b>مرحباً بك في بوت الفواتير!</b>\n\n"
        "يمكنك إنشاء:\n"
        "📄 <b>فواتير</b> - فواتير احترافية مع تفاصيل المنتجات\n"
        "💰 <b>عروض أسعار</b> - عروض أسعار مع فترة صلاحية\n"
        "🧾 <b>إيصالات استلام</b> - تأكيد الدفع أو التسليم\n"
        "📋 <b>قوالب مخصصة</b> - صمم قوالبك الخاصة\n\n"
        "اختر من القائمة أدناه أو استخدم الأوامر 👇"
    ),
    "help": (
        "📖 <b>دليل الاستخدام</b>\n\n"
        "🔹 /start - بدء البوت\n"
        "🔹 /invoice - إنشاء فاتورة جديدة\n"
        "🔹 /quote - إنشاء عرض سعر\n"
        "🔹 /receipt - إنشاء إيصال استلام\n"
        "🔹 /templates - إدارة القوالب المخصصة\n"
        "🔹 /cancel - إلغاء العملية الحالية\n"
        "🔹 /help - عرض هذا الدليل\n\n"
        "💡 <b>نصائح:</b>\n"
        "• يمكنك إضافة عدة منتجات في الفاتورة الواحدة\n"
        "• يتم حساب الضريبة تلقائياً\n"
        "• يمكنك تصدير المستندات كـ PDF أو صورة أو نص\n"
        "• أرسل /cancel في أي وقت لإلغاء العملية"
    ),
    "cancelled": "❌ تم إلغاء العملية.",
    "error": "⚠️ حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى.",
    "invalid_number": "⚠️ يرجى إدخال رقم صحيح.",
    "invalid_positive_number": "⚠️ يرجى إدخال رقم أكبر من صفر.",
}
