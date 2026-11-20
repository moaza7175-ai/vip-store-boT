"""
template_engine.py - محرك القوالب
Template rendering engine for generating text, images (Pillow), and PDFs.
Uses VIP STORE gaming services visual identity and user template.
Supports Arabic RTL text with arabic-reshaper and python-bidi.
"""

import io
import json
import logging
from pathlib import Path
from typing import Union

from PIL import Image, ImageDraw, ImageFont

from models import Invoice, Quote, Receipt, FilledTemplate, CustomTemplate, TemplateField
from config import (
    get_arabic_font_path,
    IMAGE_WIDTH,
    IMAGE_HEIGHT,
    IMAGE_BG_COLOR,
    IMAGE_TEXT_COLOR,
    IMAGE_ACCENT_COLOR,
    IMAGE_HEADER_COLOR,
    USER_DATA_DIR,
    DEFAULT_TEMPLATES_FILE,
    LOGO_PATH,
    INVOICE_TEMPLATE_PATH,
    HEADER_PATH,
    FOOTER_PATH,
)

logger = logging.getLogger(__name__)

# --- مساعدات النص العربي ---

def reshape_arabic(text: str) -> str:
    """إعادة تشكيل النص العربي لعرضه بشكل صحيح"""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        reshaped = arabic_reshaper.reshape(str(text))
        return get_display(reshaped)
    except Exception as e:
        logger.error(f"خطأ في إعادة تشكيل النص العربي: {e}")
        return str(text)


def format_currency(amount: float) -> str:
    """تنسيق المبلغ المالي"""
    return f"{amount:,.2f}"


# =============================================================================
#  توليد النص (Plain Text لرسائل تيليجرام)
# =============================================================================

def render_invoice_text(invoice: Invoice) -> str:
    """توليد فاتورة كنص للمحادثة"""
    lines = [
        "═" * 40,
        "      🎮 VIP GAMING SERVICES",
        f"         📄 {invoice.doc_type}",
        "═" * 40,
        f"رقم الفاتورة: {invoice.invoice_number}",
    ]
    if invoice.order_number:
        lines.append(f"🔢 رقم الطلب: #{invoice.order_number}")
    lines.extend([
        f"التاريخ: {invoice.date}",
        "─" * 40,
        "👤 بيانات العميل:",
        f"   الاسم: {invoice.customer.name}",
    ])
    if invoice.customer.phone:
        lines.append(f"   الهاتف: {invoice.customer.phone}")

    if invoice.account_name or invoice.player_id:
        lines.append("─" * 40)
        lines.append("🎮 بيانات الحساب:")
        if invoice.account_name:
            lines.append(f"   اسم الحساب: {invoice.account_name}")
        if invoice.player_id:
            lines.append(f"   ID الحساب: {invoice.player_id}")

    lines.extend([
        "─" * 40,
        "📦 المنتجات:",
        f"{'المنتج':<20} {'الكمية':>6} {'السعر':>8} {'الإجمالي':>8}",
        "─" * 40,
    ])

    for item in invoice.items:
        lines.append(
            f"{item.name:<20} {item.quantity:>6.0f} {format_currency(item.unit_price):>8} {format_currency(item.total):>8}"
        )

    lines.extend([
        "─" * 40,
        f"المجموع الفرعي: {format_currency(invoice.subtotal)}",
        f"الضريبة ({invoice.tax_rate*100:.0f}%): {format_currency(invoice.tax_amount)}",
        "═" * 40,
        f"💰 الإجمالي: {format_currency(invoice.total)}",
        "═" * 40,
    ])

    if invoice.notes:
        lines.extend(["", f"📝 ملاحظات: {invoice.notes}"])

    return "\n".join(lines)


def render_quote_text(quote: Quote) -> str:
    """توليد عرض سعر كنص"""
    lines = [
        "═" * 40,
        f"         💰 {quote.doc_type}",
        "═" * 40,
        f"رقم العرض: {quote.quote_number}",
        f"التاريخ: {quote.date}",
        f"صالح حتى: {quote.expiry_date}",
        "─" * 40,
        "👤 بيانات العميل:",
        f"   الاسم: {quote.customer.name}",
    ]
    if quote.customer.phone:
        lines.append(f"   الهاتف: {quote.customer.phone}")

    lines.extend([
        "─" * 40,
        "📦 البنود:",
        f"{'البند':<20} {'الكمية':>6} {'السعر':>8} {'الإجمالي':>8}",
        "─" * 40,
    ])

    for item in quote.items:
        lines.append(
            f"{item.name:<20} {item.quantity:>6.0f} {format_currency(item.unit_price):>8} {format_currency(item.total):>8}"
        )

    lines.extend([
        "═" * 40,
        f"💰 الإجمالي: {format_currency(quote.total)}",
        "═" * 40,
    ])

    if quote.terms:
        lines.extend(["", f"📋 الشروط والأحكام:", f"   {quote.terms}"])
    if quote.notes:
        lines.extend(["", f"📝 ملاحظات: {quote.notes}"])

    return "\n".join(lines)


def render_receipt_text(receipt: Receipt) -> str:
    """توليد إيصال استلام كنص"""
    lines = [
        "═" * 40,
        f"         🧾 {receipt.doc_type}",
        "═" * 40,
        f"رقم الإيصال: {receipt.receipt_number}",
        f"التاريخ: {receipt.date}",
        "─" * 40,
        "👤 المستلم:",
        f"   الاسم: {receipt.customer.name}",
    ]

    lines.extend([
        "─" * 40,
        f"💰 المبلغ: {format_currency(receipt.amount)}",
        f"💳 طريقة الدفع: {receipt.payment_method}",
    ])

    if receipt.description:
        lines.append(f"📋 الوصف: {receipt.description}")

    lines.append("═" * 40)

    if receipt.notes:
        lines.extend([f"📝 ملاحظات: {receipt.notes}"])

    return "\n".join(lines)


def render_custom_template_text(filled: FilledTemplate) -> str:
    """توليد مستند من قالب مخصص كنص"""
    lines = [
        "═" * 40,
        f"         📋 {filled.template.name}",
        "═" * 40,
        f"رقم المستند: {filled.doc_number}",
        f"التاريخ: {filled.date}",
        "─" * 40,
    ]

    for f in filled.template.fields:
        value = filled.values.get(f.name, "—")
        lines.append(f"{f.name}: {value}")

    lines.append("═" * 40)
    return "\n".join(lines)


# =============================================================================
#  مساعدات الرسم والتصميم (Pillow)
# =============================================================================

def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """تحميل خط عربي عالي الجودة مع دعم الخط العريض"""
    font_name = "segoeuib.ttf" if bold else "segoeui.ttf"
    font_path = Path("C:/Windows/Fonts") / font_name
    if not font_path.exists():
        font_name = "arialbd.ttf" if bold else "arial.ttf"
        font_path = Path("C:/Windows/Fonts") / font_name
    if not font_path.exists():
        font_path = get_arabic_font_path()
    if font_path and Path(font_path).exists():
        try:
            return ImageFont.truetype(str(font_path), size)
        except Exception:
            pass
    return ImageFont.load_default()


def _draw_text_rtl(draw: ImageDraw.ImageDraw, xy: tuple, text: str, font, fill: str, anchor: str = "rt"):
    """رسم نص عربي من اليمين لليسار بدون محارف خفية"""
    reshaped = reshape_arabic(text)
    draw.text(xy, reshaped, font=font, fill=fill, anchor=anchor)


def _draw_text_centered(draw: ImageDraw.ImageDraw, xy: tuple, text: str, font, fill: str):
    """رسم نص في المنتصف تماماً"""
    reshaped = reshape_arabic(text)
    draw.text(xy, reshaped, font=font, fill=fill, anchor="mm")


def _draw_background_decorations(img: Image.Image, draw: ImageDraw.ImageDraw, width: int, height: int):
    """رسم العلامة المائية والخطوط الهندسية المتناسقة للخلفية (للقوالب الاحتياطية)"""
    draw.polygon([(0, 130), (140, 130), (0, 270)], fill="#edf2f8")
    draw.polygon([(0, 130), (90, 130), (0, 220)], fill="#e2ebf5")
    draw.polygon([(0, height - 220), (120, height - 90), (0, height - 90)], fill="#edf2f8")
    draw.line([(0, 290), (160, 130)], fill="#d5e2f0", width=2)
    draw.line([(0, height - 240), (140, height - 90)], fill="#d5e2f0", width=2)

    if LOGO_PATH.exists():
        try:
            with Image.open(LOGO_PATH) as logo:
                logo_w = logo.convert("RGBA")
                wm_size = (480, 480)
                logo_w = logo_w.resize(wm_size, Image.Resampling.LANCZOS)
                r, g, b, a = logo_w.split()
                a = a.point(lambda p: int(p * 0.08))
                watermark = Image.merge("RGBA", (r, g, b, a))
                wm_x = (width - wm_size[0]) // 2
                wm_y = (height - wm_size[1]) // 2 + 30
                img.paste(watermark, (wm_x, wm_y), watermark)
        except Exception as e:
            logger.warning(f"Watermark error: {e}")


def _paste_header_and_footer(img: Image.Image, draw: ImageDraw.ImageDraw, width: int, height: int, header_h: int = 135, footer_h: int = 90):
    """تركيب الهيدر والفوتر الخاصين بـ VIP GAMING SERVICES (للقوالب الاحتياطية)"""
    if HEADER_PATH.exists():
        try:
            header_img = Image.open(HEADER_PATH).convert("RGBA")
            header_resized = header_img.resize((width, header_h), Image.Resampling.LANCZOS)
            img.paste(header_resized, (0, 0), header_resized)
        except Exception as e:
            draw.rectangle([(0, 0), (width, header_h)], fill="#050d20")
    else:
        draw.rectangle([(0, 0), (width, header_h)], fill="#050d20")

    footer_y = height - footer_h
    if FOOTER_PATH.exists():
        try:
            footer_img = Image.open(FOOTER_PATH).convert("RGBA")
            footer_resized = footer_img.resize((width, footer_h), Image.Resampling.LANCZOS)
            img.paste(footer_resized, (0, footer_y), footer_resized)
        except Exception as e:
            draw.rectangle([(0, footer_y), (width, height)], fill="#031b47")
    else:
        draw.rectangle([(0, footer_y), (width, height)], fill="#031b47")


# =============================================================================
#  توليد الفاتورة الاحترافية على قالب VIP STORE (Pillow Image & PDF)
# =============================================================================

def render_invoice_pillow_image(invoice: Invoice) -> Image.Image:
    """
    رسم فاتورة VIP STORE على قالب الخلفية المخصص بنسبة A4 وبدقة فائقة.
    يتم ملء كل الحقول بدقة دون أي مربعات فارغة أو أخطاء نصوص.
    """
    if INVOICE_TEMPLATE_PATH.exists():
        img = Image.open(str(INVOICE_TEMPLATE_PATH)).convert("RGB")
    else:
        img = Image.new("RGB", (724, 1024), "#f9fbfd")
        draw_temp = ImageDraw.Draw(img)
        _draw_background_decorations(img, draw_temp, 724, 1024)
        _paste_header_and_footer(img, draw_temp, 724, 1024, header_h=135, footer_h=90)

    draw = ImageDraw.Draw(img)
    items = invoice.items if invoice.items else []
    row_h = 49
    extra_rows = max(0, len(items) - 1)
    extra_height = extra_rows * row_h

    # خطوط النظام
    f_brand_title = _get_font(21, bold=True)
    f_brand_sub = _get_font(12, bold=False)
    f_doc_title = _get_font(22, bold=True)
    f_sec_title = _get_font(16, bold=True)
    f_bold_md = _get_font(15, bold=True)
    f_reg_md = _get_font(14, bold=False)
    f_total_btn = _get_font(21, bold=True)
    f_footer = _get_font(11, bold=True)

    # 1. شعار واسم المتجر في الهيدر بجوار لوجو VIP المضيء
    draw.text((220, 44), "VIP GAMING SERVICES", font=f_brand_title, fill="#FFFFFF")
    draw.text((225, 72), "PLAY  *  TOP UP  *  ENJOY", font=f_brand_sub, fill="#00d2ff")

    right_x = 690
    curr_y = 145

    # 2. القسم الأول: عنوان الفاتورة والطلب والتاريخ
    doc_title = "فاتورة VIP STORE"
    _draw_text_rtl(draw, (right_x, curr_y), doc_title, f_doc_title, "#092a53", anchor="rt")
    curr_y += 32
    draw.line([(right_x - 190, curr_y), (right_x, curr_y)], fill="#d35400", width=3)
    curr_y += 18

    # رقم الطلب والتاريخ (تنسيق نصوص نظيف بدون محارف Unicode مخفية)
    order_val = invoice.order_number if invoice.order_number else invoice.invoice_number
    _draw_text_rtl(draw, (right_x, curr_y), f"#{order_val} :رقم الطلب", f_bold_md, "#1a252f", anchor="rt")
    curr_y += 28

    _draw_text_rtl(draw, (right_x, curr_y), f"التاريخ: {invoice.date}", f_bold_md, "#1a252f", anchor="rt")

    # 3. القسم الثاني: بيانات العميل والحساب داخل اللعبة
    curr_y = 280
    _draw_text_rtl(draw, (right_x, curr_y), "بيانات العميل:", f_sec_title, "#092a53", anchor="rt")
    curr_y += 28

    _draw_text_rtl(draw, (right_x, curr_y), f"الاسم: {invoice.customer.name}", f_bold_md, "#2c3e50", anchor="rt")
    curr_y += 26

    if invoice.customer.phone:
        _draw_text_rtl(draw, (right_x, curr_y), f"{invoice.customer.phone} :الهاتف", f_bold_md, "#2c3e50", anchor="rt")
        curr_y += 26

    if invoice.account_name or invoice.player_id:
        acc_parts = []
        if invoice.player_id:
            acc_parts.append(f"ID: {invoice.player_id}")
        if invoice.account_name:
            acc_parts.append(f"{invoice.account_name} :اسم الحساب")
        acc_text = "  |  ".join(acc_parts)
        _draw_text_rtl(draw, (right_x, curr_y), acc_text, f_bold_md, "#0077b6", anchor="rt")

    # 4. جدول المنتجات
    _draw_text_rtl(draw, (right_x, 448), "المنتجات:", f_sec_title, "#092a53", anchor="rt")

    # مراكز الأعمدة (متطابقة تماماً مع أعمدة القالب المطبوعة مسبقاً)
    c_tot = 117
    c_price = 292
    c_qty = 444
    c_prod = 604
    th_center_y = (478 + 515) // 2

    _draw_text_centered(draw, (c_prod, th_center_y), "المنتج", f_bold_md, "#FFFFFF")
    _draw_text_centered(draw, (c_qty, th_center_y), "الكمية", f_bold_md, "#FFFFFF")
    _draw_text_centered(draw, (c_price, th_center_y), "السعر", f_bold_md, "#FFFFFF")
    _draw_text_centered(draw, (c_tot, th_center_y), "الإجمالي", f_bold_md, "#FFFFFF")

    # إذا كانت هناك صفوف إضافية في الجدول، نغطي شريط الإجمالي القديم حتى لا يتعارض
    if extra_rows > 0:
        clean_patch = img.crop((20, 615, 704, 665)).resize((684, 57))
        img.paste(clean_patch, (20, 675))

    start_y = 516
    for idx, item in enumerate(items):
        r_y = start_y + (idx * row_h)
        center_y = r_y + (row_h // 2)

        # رسم صفوف إضافية إذا كان هناك أكثر من منتج واحد
        if idx > 0:
            draw.rectangle([(26, r_y), (697, r_y + row_h)], fill="#ffffff", outline="#092a53", width=1)
            draw.line([(208, r_y), (208, r_y + row_h)], fill="#092a53", width=1)
            draw.line([(376, r_y), (376, r_y + row_h)], fill="#092a53", width=1)
            draw.line([(512, r_y), (512, r_y + row_h)], fill="#092a53", width=1)

        name = item.name
        qty = item.quantity
        price = item.unit_price
        line_total = item.total

        _draw_text_centered(draw, (c_prod, center_y), str(name), f_bold_md, "#111111")
        _draw_text_centered(draw, (c_qty, center_y), f"{qty:g}", f_reg_md, "#111111")
        _draw_text_centered(draw, (c_price, center_y), f"{price:,.2f}", f_reg_md, "#111111")
        _draw_text_centered(draw, (c_tot, center_y), f"{line_total:,.2f}", f_bold_md, "#111111")

    # 5. الإجماليات
    tot_y = 588 + extra_height
    _draw_text_rtl(draw, (right_x, tot_y), f"المجموع الفرعي: {invoice.subtotal:,.2f}", f_bold_md, "#1a252f", anchor="rt")
    tot_y += 28

    if invoice.tax_rate > 0:
        tax_str = f"{invoice.tax_rate * 100:.2f}%"
        _draw_text_rtl(draw, (right_x, tot_y), f"الضريبة ({tax_str}): {invoice.tax_amount:,.2f}", f_bold_md, "#1a252f", anchor="rt")
    else:
        _draw_text_rtl(draw, (right_x, tot_y), "الضريبة (0.00%): 0.00", f_bold_md, "#1a252f", anchor="rt")

    # شريط الإجمالي الكحلي المميز
    btn_center_y = (680 + 727) // 2 + extra_height
    if extra_rows > 0:
        draw.rounded_rectangle([(35, btn_center_y - 24), (695, btn_center_y + 24)], radius=8, fill="#092a53")

    total_text = f"الإجمالي: {invoice.total:,.2f}"
    _draw_text_centered(draw, (366, btn_center_y), total_text, f_total_btn, "#ffb86c")

    # 6. الملاحظات
    notes_y = 755 + extra_height
    if invoice.notes:
        _draw_text_rtl(draw, (right_x, notes_y), f"ملاحظات: {invoice.notes}", f_bold_md, "#092a53", anchor="rt")

    # 7. شريط الفوتر السفلي
    footer_text_y = 988
    draw.text((45, footer_text_y - 7), "THANK YOU FOR YOUR TRUST", font=f_footer, fill="#FFFFFF")
    _draw_text_rtl(draw, (right_x, footer_text_y), "VIP GAMING SERVICES", f_footer, "#FFFFFF", anchor="rt")

    return img


def render_invoice_image(invoice: Invoice) -> bytes:
    """توليد صورة الفاتورة عالية الجودة كـ PNG bytes"""
    img = render_invoice_pillow_image(invoice)
    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def render_invoice_pdf(invoice: Invoice) -> bytes:
    """توليد ملف PDF عالي الجودة متطابق 100% مع صورة الفاتورة وقالب VIP STORE"""
    img = render_invoice_pillow_image(invoice)
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=150.0)
    return buf.getvalue()


# =============================================================================
#  توليد عروض الأسعار والإيصالات والقوالب المخصصة
# =============================================================================

def render_quote_image(quote: Quote) -> bytes:
    """توليد صورة عرض سعر بتصميم متناسق"""
    WIDTH = 800
    margin_x = 45
    right_x = WIDTH - margin_x
    row_height = 42

    num_items = max(1, len(quote.items))
    table_height = 40 + (num_items * row_height)
    base_h = 700 + table_height + (35 if quote.notes or quote.terms else 0)
    HEIGHT = max(980, base_h)

    img = Image.new("RGB", (WIDTH, HEIGHT), "#f9fbfd")
    draw = ImageDraw.Draw(img)

    _draw_background_decorations(img, draw, WIDTH, HEIGHT)
    _paste_header_and_footer(img, draw, WIDTH, HEIGHT, header_h=135, footer_h=90)

    font_title_bold = _get_font(23, bold=True)
    font_bold_lg = _get_font(18, bold=True)
    font_bold_md = _get_font(16, bold=True)
    font_regular_md = _get_font(15, bold=False)
    font_total_btn = _get_font(21, bold=True)

    curr_y = 135 + 20

    _draw_text_rtl(draw, (right_x, curr_y), f"{quote.doc_type} - VIP GAMING SERVICES", font_title_bold, "#092a53", anchor="rt")
    curr_y += 36
    draw.line([(right_x - 300, curr_y), (right_x - 85, curr_y)], fill="#d35400", width=3)
    curr_y += 18

    _draw_text_rtl(draw, (right_x, curr_y), f"#{quote.quote_number} :رقم العرض", font_bold_md, "#1a252f", anchor="rt")
    curr_y += 28

    _draw_text_rtl(draw, (right_x, curr_y), f"صالح حتى: {quote.expiry_date}", font_bold_md, "#d35400", anchor="rt")
    curr_y += 28

    _draw_text_rtl(draw, (right_x, curr_y), f"التاريخ: {quote.date}", font_bold_md, "#1a252f", anchor="rt")
    curr_y += 34

    draw.line([(margin_x, curr_y), (right_x, curr_y)], fill="#dbe3ec", width=1)
    curr_y += 20

    _draw_text_rtl(draw, (right_x, curr_y), "بيانات العميل:", font_bold_lg, "#092a53", anchor="rt")
    curr_y += 30

    _draw_text_rtl(draw, (right_x, curr_y), f"الاسم: {quote.customer.name}", font_bold_md, "#2c3e50", anchor="rt")
    curr_y += 28

    if quote.customer.phone:
        _draw_text_rtl(draw, (right_x, curr_y), f"{quote.customer.phone} :الهاتف", font_bold_md, "#2c3e50", anchor="rt")
        curr_y += 30

    draw.line([(margin_x, curr_y), (right_x, curr_y)], fill="#dbe3ec", width=1)
    curr_y += 20

    _draw_text_rtl(draw, (right_x, curr_y), "البنود:", font_bold_lg, "#092a53", anchor="rt")
    curr_y += 28

    col_w_product = 280
    col_w_qty = 110
    col_w_price = 150
    col_w_total = 170

    col_x_product_r = right_x
    col_x_product_l = col_x_product_r - col_w_product
    col_x_qty_l = col_x_product_l - col_w_qty
    col_x_price_l = col_x_qty_l - col_w_price
    col_x_total_l = margin_x

    center_col_prod = col_x_product_l + (col_w_product // 2)
    center_col_qty = col_x_qty_l + (col_w_qty // 2)
    center_col_price = col_x_price_l + (col_w_price // 2)
    center_col_total = col_x_total_l + (col_w_total // 2)

    th_h = 38
    th_y1 = curr_y
    th_y2 = curr_y + th_h
    center_th_y = th_y1 + (th_h // 2)

    draw.rounded_rectangle([(margin_x, th_y1), (right_x, th_y2)], radius=7, fill="#092a53")

    _draw_text_centered(draw, (center_col_prod, center_th_y), "البند", font_bold_md, "#FFFFFF")
    _draw_text_centered(draw, (center_col_qty, center_th_y), "الكمية", font_bold_md, "#FFFFFF")
    _draw_text_centered(draw, (center_col_price, center_th_y), "السعر", font_bold_md, "#FFFFFF")
    _draw_text_centered(draw, (center_col_total, center_th_y), "الإجمالي", font_bold_md, "#FFFFFF")

    curr_y += th_h

    for idx, item in enumerate(quote.items):
        tr_y1 = curr_y
        tr_y2 = curr_y + row_height
        center_tr_y = tr_y1 + (row_height // 2)
        row_bg = "#ffffff" if idx % 2 == 0 else "#f6f9fc"

        draw.rectangle([(margin_x, tr_y1), (right_x, tr_y2)], fill=row_bg, outline="#c7d5e4", width=1)
        draw.line([(col_x_product_l, tr_y1), (col_x_product_l, tr_y2)], fill="#c7d5e4", width=1)
        draw.line([(col_x_qty_l, tr_y1), (col_x_qty_l, tr_y2)], fill="#c7d5e4", width=1)
        draw.line([(col_x_price_l, tr_y1), (col_x_price_l, tr_y2)], fill="#c7d5e4", width=1)

        _draw_text_centered(draw, (center_col_prod, center_tr_y), item.name, font_bold_md, "#111111")
        _draw_text_centered(draw, (center_col_qty, center_tr_y), f"{item.quantity:g}", font_regular_md, "#111111")
        _draw_text_centered(draw, (center_col_price, center_tr_y), format_currency(item.unit_price), font_regular_md, "#111111")
        _draw_text_centered(draw, (center_col_total, center_tr_y), format_currency(item.total), font_bold_md, "#111111")

        curr_y += row_height

    curr_y += 18
    _draw_text_rtl(draw, (right_x, curr_y), f"الإجمالي: {format_currency(quote.total)}", font_total_btn, "#092a53", anchor="rt")
    curr_y += 35

    if quote.terms:
        _draw_text_rtl(draw, (right_x, curr_y), f"الشروط: {quote.terms}", font_bold_md, "#092a53", anchor="rt")
        curr_y += 25

    if quote.notes:
        _draw_text_rtl(draw, (right_x, curr_y), f"ملاحظات: {quote.notes}", font_bold_md, "#092a53", anchor="rt")

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def render_receipt_image(receipt: Receipt) -> bytes:
    """توليد صورة إيصال استلام بتصميم متناسق"""
    WIDTH = 800
    HEIGHT = 750
    margin_x = 45
    right_x = WIDTH - margin_x

    img = Image.new("RGB", (WIDTH, HEIGHT), "#f9fbfd")
    draw = ImageDraw.Draw(img)

    _draw_background_decorations(img, draw, WIDTH, HEIGHT)
    _paste_header_and_footer(img, draw, WIDTH, HEIGHT, header_h=135, footer_h=90)

    font_title_bold = _get_font(23, bold=True)
    font_bold_lg = _get_font(18, bold=True)
    font_bold_md = _get_font(16, bold=True)
    font_amount = _get_font(24, bold=True)

    curr_y = 135 + 20

    _draw_text_rtl(draw, (right_x, curr_y), f"{receipt.doc_type} - VIP GAMING SERVICES", font_title_bold, "#092a53", anchor="rt")
    curr_y += 36
    draw.line([(right_x - 300, curr_y), (right_x - 85, curr_y)], fill="#d35400", width=3)
    curr_y += 18

    _draw_text_rtl(draw, (right_x, curr_y), f"#{receipt.receipt_number} :رقم الإيصال", font_bold_md, "#1a252f", anchor="rt")
    curr_y += 28

    _draw_text_rtl(draw, (right_x, curr_y), f"التاريخ: {receipt.date}", font_bold_md, "#1a252f", anchor="rt")
    curr_y += 34

    draw.line([(margin_x, curr_y), (right_x, curr_y)], fill="#dbe3ec", width=1)
    curr_y += 20

    _draw_text_rtl(draw, (right_x, curr_y), "بيانات المستلم:", font_bold_lg, "#092a53", anchor="rt")
    curr_y += 30

    _draw_text_rtl(draw, (right_x, curr_y), f"الاسم: {receipt.customer.name}", font_bold_md, "#2c3e50", anchor="rt")
    curr_y += 28

    _draw_text_rtl(draw, (right_x, curr_y), f"طريقة الدفع: {receipt.payment_method}", font_bold_md, "#1a252f", anchor="rt")
    curr_y += 28

    if receipt.description:
        _draw_text_rtl(draw, (right_x, curr_y), f"الوصف: {receipt.description}", font_bold_md, "#1a252f", anchor="rt")
        curr_y += 30

    draw.line([(margin_x, curr_y), (right_x, curr_y)], fill="#dbe3ec", width=1)
    curr_y += 25

    btn_h = 50
    draw.rounded_rectangle([(margin_x, curr_y), (right_x, curr_y + btn_h)], radius=10, fill="#092a53")
    _draw_text_centered(draw, (WIDTH // 2, curr_y + (btn_h // 2)), f"المبلغ المستلم: {format_currency(receipt.amount)}", font_amount, "#ffb86c")
    curr_y += btn_h + 25

    if receipt.notes:
        _draw_text_rtl(draw, (right_x, curr_y), f"ملاحظات: {receipt.notes}", font_bold_md, "#092a53", anchor="rt")

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def render_custom_template_image(filled: FilledTemplate) -> bytes:
    """توليد صورة مستند من قالب مخصص بتصميم متناسق"""
    WIDTH = 800
    fields_count = len(filled.template.fields)
    base_h = 550 + (fields_count * 45)
    HEIGHT = max(800, base_h)
    margin_x = 45
    right_x = WIDTH - margin_x

    img = Image.new("RGB", (WIDTH, HEIGHT), "#f9fbfd")
    draw = ImageDraw.Draw(img)

    _draw_background_decorations(img, draw, WIDTH, HEIGHT)
    _paste_header_and_footer(img, draw, WIDTH, HEIGHT, header_h=135, footer_h=90)

    font_title_bold = _get_font(23, bold=True)
    font_bold_md = _get_font(16, bold=True)
    font_regular_md = _get_font(15, bold=False)

    curr_y = 135 + 20

    _draw_text_rtl(draw, (right_x, curr_y), f"{filled.template.name} - VIP GAMING SERVICES", font_title_bold, "#092a53", anchor="rt")
    curr_y += 36
    draw.line([(right_x - 300, curr_y), (right_x - 85, curr_y)], fill="#d35400", width=3)
    curr_y += 18

    _draw_text_rtl(draw, (right_x, curr_y), f"#{filled.doc_number} :رقم المستند", font_bold_md, "#1a252f", anchor="rt")
    curr_y += 28

    _draw_text_rtl(draw, (right_x, curr_y), f"التاريخ: {filled.date}", font_bold_md, "#1a252f", anchor="rt")
    curr_y += 34

    draw.line([(margin_x, curr_y), (right_x, curr_y)], fill="#dbe3ec", width=1)
    curr_y += 25

    for f in filled.template.fields:
        val = filled.values.get(f.name, "—")
        _draw_text_rtl(draw, (right_x, curr_y), f"{f.name}:", font_bold_md, "#092a53", anchor="rt")
        curr_y += 26
        _draw_text_rtl(draw, (right_x, curr_y), str(val), font_regular_md, "#2c3e50", anchor="rt")
        curr_y += 28
        draw.line([(margin_x, curr_y), (right_x, curr_y)], fill="#edf2f8", width=1)
        curr_y += 15

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def render_quote_pdf(quote: Quote) -> bytes:
    """توليد ملف PDF لعرض السعر من صورة Pillow المتطابقة"""
    img_data = render_quote_image(quote)
    img = Image.open(io.BytesIO(img_data))
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=150.0)
    return buf.getvalue()


def render_receipt_pdf(receipt: Receipt) -> bytes:
    """توليد ملف PDF لإيصال الاستلام من صورة Pillow المتطابقة"""
    img_data = render_receipt_image(receipt)
    img = Image.open(io.BytesIO(img_data))
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=150.0)
    return buf.getvalue()


def render_custom_template_pdf(filled: FilledTemplate) -> bytes:
    """توليد ملف PDF لقالب مخصص من صورة Pillow المتطابقة"""
    img_data = render_custom_template_image(filled)
    img = Image.open(io.BytesIO(img_data))
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=150.0)
    return buf.getvalue()


# =============================================================================
#  إدارة القوالب المخصصة (تخزين JSON)
# =============================================================================

def _get_user_templates_path(user_id: int) -> Path:
    """الحصول على مسار ملف قوالب المستخدم"""
    return USER_DATA_DIR / f"templates_{user_id}.json"


def load_user_templates(user_id: int) -> list[CustomTemplate]:
    """تحميل قوالب المستخدم"""
    path = _get_user_templates_path(user_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [CustomTemplate.from_dict(t) for t in data]
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"خطأ في تحميل قوالب المستخدم {user_id}: {e}")
        return []


def save_user_templates(user_id: int, templates: list[CustomTemplate]) -> None:
    """حفظ قوالب المستخدم"""
    path = _get_user_templates_path(user_id)
    data = [t.to_dict() for t in templates]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def add_user_template(user_id: int, template: CustomTemplate) -> None:
    """إضافة قالب جديد للمستخدم"""
    templates = load_user_templates(user_id)
    templates.append(template)
    save_user_templates(user_id, templates)


def delete_user_template(user_id: int, template_id: str) -> bool:
    """حذف قالب المستخدم"""
    templates = load_user_templates(user_id)
    original_len = len(templates)
    templates = [t for t in templates if t.template_id != template_id]
    if len(templates) < original_len:
        save_user_templates(user_id, templates)
        return True
    return False


def load_default_templates() -> list[CustomTemplate]:
    """تحميل القوالب الافتراضية"""
    if not DEFAULT_TEMPLATES_FILE.exists():
        return []
    try:
        data = json.loads(DEFAULT_TEMPLATES_FILE.read_text(encoding="utf-8"))
        return [CustomTemplate.from_dict(t) for t in data.get("templates", [])]
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"خطأ في تحميل القوالب الافتراضية: {e}")
        return []
