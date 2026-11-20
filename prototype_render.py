"""
prototype_render.py - تجربة وتدقيق تصميم الفاتورة المطابق تماماً لطلب المستخدم
"""
import io
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import arabic_reshaper
from bidi.algorithm import get_display

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

HEADER_PATH = ASSETS_DIR / "template_header.png"
FOOTER_PATH = ASSETS_DIR / "template_footer.png"
LOGO_PATH = ASSETS_DIR / "logo.jpg"

def reshape_text(text: str) -> str:
    """إعادة تشكيل النص العربي لعرضه بشكل صحيح في بايلو"""
    try:
        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)
    except Exception:
        return text

def get_font(size: int, bold: bool = False):
    """تحميل خط عربي عالي الجودة"""
    font_name = "segoeuib.ttf" if bold else "segoeui.ttf"
    font_path = Path("C:/Windows/Fonts") / font_name
    if not font_path.exists():
        font_name = "arialbd.ttf" if bold else "arial.ttf"
        font_path = Path("C:/Windows/Fonts") / font_name
    try:
        return ImageFont.truetype(str(font_path), size)
    except Exception:
        return ImageFont.load_default()

def draw_text_rtl(draw: ImageDraw.ImageDraw, xy: tuple, text: str, font, fill: str, anchor: str = "rt"):
    """رسم نص عربي من اليمين لليسار"""
    display_str = reshape_text(text)
    draw.text(xy, display_str, font=font, fill=fill, anchor=anchor)

def draw_text_centered(draw: ImageDraw.ImageDraw, xy: tuple, text: str, font, fill: str):
    """رسم نص عربي في المنتصف تماماً"""
    display_str = reshape_text(text)
    draw.text(xy, display_str, font=font, fill=fill, anchor="mm")

def create_styled_invoice(
    order_number: str = "VIPDHJFDKJMH",
    date_str: str = "20-11-2026 03:32",
    customer_name: str = "MOAZ AMR",
    customer_phone: str = "01062318668",
    items: list = None,
    tax_rate: float = 0.0,
    notes: str = ""
) -> Image.Image:
    if items is None:
        items = [
            {"name": "325 BONUS", "qty": 3, "price": 300.0, "total": 900.0}
        ]

    WIDTH = 800
    
    # حساب الأبعاد بدقة لمنع الفراغات الزائدة أو التكدس
    margin_x = 45
    content_width = WIDTH - (margin_x * 2)  # 710px
    
    # حساب الارتفاع الديناميكي المتناسق
    row_height = 42
    items_table_height = 42 + (len(items) * row_height)  # هيدر + صفوف
    
    # الارتفاع الكلي
    base_content_height = 680 + items_table_height
    HEIGHT = max(1000, base_content_height)  # أبعاد متناسقة ومريحة للعين
    
    # 1. إنشاء الخلفية
    img = Image.new("RGB", (WIDTH, HEIGHT), "#f9fbfd")
    draw = ImageDraw.Draw(img)
    
    # 2. خطوط هندسية جانبية خفيفة (Geometric Gaming Accents)
    # زاوية علوية يسارية
    draw.polygon([(0, 130), (140, 130), (0, 270)], fill="#edf2f8")
    draw.polygon([(0, 130), (90, 130), (0, 220)], fill="#e2ebf5")
    # زاوية سفلية يسارية
    draw.polygon([(0, HEIGHT - 220), (120, HEIGHT - 90), (0, HEIGHT - 90)], fill="#edf2f8")
    # خطوط دقيقة أنيقة
    draw.line([(0, 290), (160, 130)], fill="#d5e2f0", width=2)
    draw.line([(0, HEIGHT - 240), (140, HEIGHT - 90)], fill="#d5e2f0", width=2)
    
    # 3. العلامة المائية في المنتصف (Watermark)
    if LOGO_PATH.exists():
        try:
            with Image.open(LOGO_PATH) as logo:
                logo_w = logo.convert("RGBA")
                wm_size = (480, 480)
                logo_w = logo_w.resize(wm_size, Image.Resampling.LANCZOS)
                
                # تخفيف الشفافية جداً (watermark opacity ~8%)
                r, g, b, a = logo_w.split()
                a = a.point(lambda p: int(p * 0.08))
                watermark = Image.merge("RGBA", (r, g, b, a))
                
                # موقع التوسيط
                wm_x = (WIDTH - wm_size[0]) // 2
                wm_y = (HEIGHT - wm_size[1]) // 2 + 30
                img.paste(watermark, (wm_x, wm_y), watermark)
        except Exception as e:
            print("Watermark error:", e)

    # 4. رأس الصفحة (Header)
    header_h = 135
    if HEADER_PATH.exists():
        try:
            header_img = Image.open(HEADER_PATH).convert("RGBA")
            # تغيير حجم الهيدر ليتناسب تماماً مع عرض 800
            header_resized = header_img.resize((WIDTH, header_h), Image.Resampling.LANCZOS)
            img.paste(header_resized, (0, 0), header_resized)
        except Exception as e:
            print("Header error:", e)
    else:
        draw.rectangle([(0, 0), (WIDTH, header_h)], fill="#050d20")

    # 5. تذييل الصفحة (Footer)
    footer_h = 90
    footer_y = HEIGHT - footer_h
    if FOOTER_PATH.exists():
        try:
            footer_img = Image.open(FOOTER_PATH).convert("RGBA")
            footer_resized = footer_img.resize((WIDTH, footer_h), Image.Resampling.LANCZOS)
            img.paste(footer_resized, (0, footer_y), footer_resized)
        except Exception as e:
            print("Footer error:", e)
    else:
        draw.rectangle([(0, footer_y), (WIDTH, HEIGHT)], fill="#031b47")

    # الخطوط المستخدمة
    font_title_bold = get_font(23, bold=True)
    font_brand_title = get_font(21, bold=True)
    font_bold_lg = get_font(18, bold=True)
    font_bold_md = get_font(16, bold=True)
    font_regular_md = get_font(15, bold=False)
    font_regular_sm = get_font(14, bold=False)
    font_bold_sm = get_font(14, bold=True)
    font_total_btn = get_font(21, bold=True)

    curr_y = header_h + 20
    right_x = WIDTH - margin_x

    # 6. عنوان الفاتورة: "فاتورة - VIP GAMING SERVICES"
    # كتابة "VIP GAMING SERVICES" بلون نحاسي/برتقالي و "فاتورة -" بلون كحلي داكن
    title_prefix = "فاتورة -"
    title_suffix = " VIP GAMING SERVICES"
    
    # رسم العنوان بالكامل
    full_title = f"{title_prefix}{title_suffix}"
    draw_text_rtl(draw, (right_x, curr_y), full_title, font_title_bold, "#092a53", anchor="rt")
    
    # خط تزييني برتقالي أنيق تحت عبارة VIP GAMING SERVICES
    curr_y += 36
    draw.line([(right_x - 300, curr_y), (right_x - 85, curr_y)], fill="#d35400", width=3)
    curr_y += 18

    # 7. رقم الطلب والتاريخ (معالجة اتجاه الرموز بذكاء لمنع القلب)
    order_label = f"رقم الطلب: #{order_number} 🧾"
    draw_text_rtl(draw, (right_x, curr_y), order_label, font_bold_md, "#1a252f", anchor="rt")
    curr_y += 28

    date_label = f"التاريخ: {date_str} 📅"
    draw_text_rtl(draw, (right_x, curr_y), date_label, font_bold_md, "#1a252f", anchor="rt")
    curr_y += 34

    # خط فاصل خفيف
    draw.line([(margin_x, curr_y), (right_x, curr_y)], fill="#dbe3ec", width=1)
    curr_y += 20

    # 8. بيانات العميل (Customer Info)
    draw_text_rtl(draw, (right_x, curr_y), "بيانات العميل: 👤", font_bold_lg, "#092a53", anchor="rt")
    curr_y += 30

    draw_text_rtl(draw, (right_x, curr_y), f"الاسم: {customer_name}", font_bold_md, "#2c3e50", anchor="rt")
    curr_y += 28

    if customer_phone:
        draw_text_rtl(draw, (right_x, curr_y), f"الهاتف: {customer_phone} 📞", font_bold_md, "#2c3e50", anchor="rt")
        curr_y += 30

    # خط فاصل خفيف
    draw.line([(margin_x, curr_y), (right_x, curr_y)], fill="#dbe3ec", width=1)
    curr_y += 20

    # 9. المنتجات (Products Table)
    draw_text_rtl(draw, (right_x, curr_y), "المنتجات: 📦", font_bold_lg, "#092a53", anchor="rt")
    curr_y += 28

    # أبعاد أعمدة الجدول (العرض الكلي = content_width = 710px)
    # ترتيب الأعمدة في التصميم (من اليمين إلى اليسار):
    # [المنتج: 280px] [الكمية: 110px] [السعر: 150px] [الإجمالي: 170px]
    col_w_product = 280
    col_w_qty = 110
    col_w_price = 150
    col_w_total = 170

    col_x_product_r = right_x
    col_x_product_l = col_x_product_r - col_w_product
    col_x_qty_l = col_x_product_l - col_w_qty
    col_x_price_l = col_x_qty_l - col_w_price
    col_x_total_l = margin_x  # col_x_price_l - col_w_total = margin_x

    # رسم رأس الجدول بشريط كحلي داكن بحواف دائرية (Rounded Header)
    th_h = 38
    th_y1 = curr_y
    th_y2 = curr_y + th_h
    
    draw.rounded_rectangle(
        [(margin_x, th_y1), (right_x, th_y2)],
        radius=7,
        fill="#092a53"
    )

    # نصوص رؤوس الأعمدة
    # مراكز الأعمدة للتوسيط
    center_col_prod = col_x_product_l + (col_w_product // 2)
    center_col_qty = col_x_qty_l + (col_w_qty // 2)
    center_col_price = col_x_price_l + (col_w_price // 2)
    center_col_total = col_x_total_l + (col_w_total // 2)
    center_th_y = th_y1 + (th_h // 2)

    draw_text_centered(draw, (center_col_prod, center_th_y), "المنتج", font_bold_md, "#FFFFFF")
    draw_text_centered(draw, (center_col_qty, center_th_y), "الكمية", font_bold_md, "#FFFFFF")
    draw_text_centered(draw, (center_col_price, center_th_y), "السعر", font_bold_md, "#FFFFFF")
    draw_text_centered(draw, (center_col_total, center_th_y), "الإجمالي", font_bold_md, "#FFFFFF")

    # فواصل بيضاء خفيفة في رأس الجدول
    draw.line([(col_x_product_l, th_y1 + 4), (col_x_product_l, th_y2 - 4)], fill="#21497a", width=1)
    draw.line([(col_x_qty_l, th_y1 + 4), (col_x_qty_l, th_y2 - 4)], fill="#21497a", width=1)
    draw.line([(col_x_price_l, th_y1 + 4), (col_x_price_l, th_y2 - 4)], fill="#21497a", width=1)

    curr_y += th_h

    # رسم صفوف المنتجات
    subtotal = 0.0
    for idx, item in enumerate(items):
        item_name = item.get("name", "")
        qty = item.get("qty", 1)
        price = item.get("price", 0.0)
        line_total = item.get("total", qty * price)
        subtotal += line_total

        tr_y1 = curr_y
        tr_y2 = curr_y + row_height
        center_tr_y = tr_y1 + (row_height // 2)

        # خلفية الصف (بيضاء مع حدود خفيفة)
        row_bg = "#ffffff" if idx % 2 == 0 else "#f6f9fc"
        draw.rectangle([(margin_x, tr_y1), (right_x, tr_y2)], fill=row_bg, outline="#c7d5e4", width=1)

        # خطوط الفواصل الرأسية
        draw.line([(col_x_product_l, tr_y1), (col_x_product_l, tr_y2)], fill="#c7d5e4", width=1)
        draw.line([(col_x_qty_l, tr_y1), (col_x_qty_l, tr_y2)], fill="#c7d5e4", width=1)
        draw.line([(col_x_price_l, tr_y1), (col_x_price_l, tr_y2)], fill="#c7d5e4", width=1)

        # كتابة بيانات المنتج
        draw_text_centered(draw, (center_col_prod, center_tr_y), str(item_name), font_bold_md, "#111111")
        draw_text_centered(draw, (center_col_qty, center_tr_y), f"{qty:g}", font_regular_md, "#111111")
        draw_text_centered(draw, (center_col_price, center_tr_y), f"{price:,.2f}", font_regular_md, "#111111")
        draw_text_centered(draw, (center_col_total, center_tr_y), f"{line_total:,.2f}", font_bold_md, "#111111")

        curr_y += row_height

    curr_y += 20

    # 10. قسم الإجماليات (Totals Section)
    tax_amount = subtotal * tax_rate
    grand_total = subtotal + tax_amount

    # المجموع الفرعي والضريبة
    draw_text_rtl(draw, (right_x, curr_y), f"المجموع الفرعي: {subtotal:,.2f}", font_bold_md, "#1a252f", anchor="rt")
    curr_y += 28

    tax_percent_str = f"{tax_rate * 100:.2f}%"
    draw_text_rtl(draw, (right_x, curr_y), f"الضريبة ({tax_percent_str}): {tax_amount:,.2f}", font_bold_md, "#1a252f", anchor="rt")
    curr_y += 34

    # زر الإجمالي الكلي (Rounded Blue Pill Button)
    btn_h = 52
    btn_y1 = curr_y
    btn_y2 = curr_y + btn_h
    btn_center_y = btn_y1 + (btn_h // 2)

    draw.rounded_rectangle(
        [(margin_x, btn_y1), (right_x, btn_y2)],
        radius=9,
        fill="#092a53"
    )

    # نص الإجمالي باللون الذهبي
    total_text = f"الإجمالي: {grand_total:,.2f}"
    draw_text_centered(draw, (WIDTH // 2, btn_center_y), total_text, font_total_btn, "#ffb86c")
    curr_y += btn_h + 25

    # 11. الملاحظات (Notes) إن وجدت
    if notes:
        draw_text_rtl(draw, (right_x, curr_y), f"ملاحظات: {notes} 📝", font_bold_md, "#092a53", anchor="rt")
        curr_y += 30

    return img

if __name__ == "__main__":
    out_img = create_styled_invoice()
    out_path = OUTPUT_DIR / "sample_styled_invoice.png"
    out_img.save(str(out_path), quality=95)
    print(f"✅ Generated sample invoice at: {out_path} (Size: {out_img.size})")
