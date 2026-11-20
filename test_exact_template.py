"""
test_exact_template.py - اختبار رسم الفاتورة على الصورة الجديدة التي رفعها المستخدم
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display
from config import ASSETS_DIR, OUTPUT_DIR

TEMPLATE_PATH = ASSETS_DIR / "invoice_template.jpg"

def reshape_text(text: str) -> str:
    try:
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text

def get_font(size: int, bold: bool = False):
    font_name = "segoeuib.ttf" if bold else "segoeui.ttf"
    font_path = Path("C:/Windows/Fonts") / font_name
    if not font_path.exists():
        font_name = "arialbd.ttf" if bold else "arial.ttf"
        font_path = Path("C:/Windows/Fonts") / font_name
    try:
        return ImageFont.truetype(str(font_path), size)
    except Exception:
        return ImageFont.load_default()

def draw_rtl(draw, xy, text, font, fill="#1a252f", anchor="rt"):
    disp = reshape_text(text)
    draw.text(xy, disp, font=font, fill=fill, anchor=anchor)

def draw_center(draw, xy, text, font, fill="#FFFFFF"):
    disp = reshape_text(text)
    draw.text(xy, disp, font=font, fill=fill, anchor="mm")

def render_on_user_template(
    order_num="VIPDHJFDKJMH",
    date_str="20-11-2026 03:32",
    cust_name="MOAZ AMR",
    phone="01062318668",
    account_name="VIP_SNIPER",
    player_id="512398741",
    items=None,
    total=900.0,
    subtotal=900.0,
    tax_rate=0.0,
    notes="تسليم فوري عبر الـ ID"
):
    if items is None:
        items = [{"name": "325 BONUS", "qty": 3, "price": 300.0, "total": 900.0}]

    img = Image.open(str(TEMPLATE_PATH)).convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = img.size

    # Fonts
    f_brand_title = get_font(21, bold=True)
    f_brand_sub = get_font(12, bold=False)
    f_doc_title = get_font(21, bold=True)
    f_sec_title = get_font(16, bold=True)
    f_bold_md = get_font(15, bold=True)
    f_reg_md = get_font(14, bold=False)
    f_total_btn = get_font(20, bold=True)

    # 1. كتابة اسم المتجر بجوار اللوجو في الهيدر
    draw.text((225, 45), "VIP GAMING SERVICES", font=f_brand_title, fill="#FFFFFF")
    draw.text((230, 72), "PLAY • TOP UP • ENJOY", font=f_brand_sub, fill="#00d2ff")

    # 2. القسم الأول: عنوان الفاتورة ورقم الطلب والتاريخ (Y: 135 إلى 260)
    curr_y = 145
    right_x = 690

    # عنوان الفاتورة
    draw_rtl(draw, (right_x, curr_y), "فاتورة VIP STORE", f_doc_title, fill="#092a53")
    curr_y += 32
    draw.line([(right_x - 180, curr_y), (right_x, curr_y)], fill="#d35400", width=3)
    curr_y += 18

    # رقم الطلب والتاريخ
    draw_rtl(draw, (right_x, curr_y), f"\u200fرقم الطلب: \u202a#{order_num}\u202c 🧾", f_bold_md, fill="#1a252f")
    curr_y += 28

    draw_rtl(draw, (right_x, curr_y), f"\u200fالتاريخ: \u202a{date_str}\u202c 📅", f_bold_md, fill="#1a252f")

    # 3. القسم الثاني: بيانات العميل والحساب (Y: 280 إلى 420)
    curr_y = 285
    draw_rtl(draw, (right_x, curr_y), "بيانات العميل: 👤", f_sec_title, fill="#092a53")
    curr_y += 28

    draw_rtl(draw, (right_x, curr_y), f"الاسم: {cust_name}", f_bold_md, fill="#2c3e50")
    curr_y += 26

    if phone:
        draw_rtl(draw, (right_x, curr_y), f"\u200fالهاتف: \u202a{phone}\u202c 📞", f_bold_md, fill="#2c3e50")
        curr_y += 26

    # بيانات الحساب داخل اللعبة
    if account_name or player_id:
        acc_info = []
        if account_name:
            acc_info.append(f"اسم الحساب: {account_name}")
        if player_id:
            acc_info.append(f"\u200fID: \u202a{player_id}\u202c")
        acc_text = "  |  ".join(acc_info) + " 🎮"
        draw_rtl(draw, (right_x, curr_y), acc_text, f_bold_md, fill="#0077b6")

    # 4. جدول المنتجات
    # عنوان جدول المنتجات
    draw_rtl(draw, (right_x, 448), "المنتجات: 📦", f_sec_title, fill="#092a53")

    # رؤوس الأعمدة (داخل الشريط الكحلي المرسوم أصلاً بالصورة)
    # مراكز الأعمدة:
    c_tot = 117
    c_price = 292
    c_qty = 444
    c_prod = 604
    th_center_y = (478 + 515) // 2

    draw_center(draw, (c_prod, th_center_y), "المنتج", f_bold_md, fill="#FFFFFF")
    draw_center(draw, (c_qty, th_center_y), "الكمية", f_bold_md, fill="#FFFFFF")
    draw_center(draw, (c_price, th_center_y), "السعر", f_bold_md, fill="#FFFFFF")
    draw_center(draw, (c_tot, th_center_y), "الإجمالي", f_bold_md, fill="#FFFFFF")

    # الصف الأول (مرسوم أصلاً في القالب من 516 إلى 565)
    row_h = 49
    start_y = 516
    for idx, item in enumerate(items):
        r_y = start_y + (idx * row_h)
        center_y = r_y + (row_h // 2)

        # إذا كان هناك أكثر من منتج، نرسم الصفوف الإضافية بخلفية مطابقة
        if idx > 0:
            draw.rectangle([(26, r_y), (697, r_y + row_h)], fill="#ffffff", outline="#092a53", width=1)
            draw.line([(208, r_y), (208, r_y + row_h)], fill="#092a53", width=1)
            draw.line([(376, r_y), (376, r_y + row_h)], fill="#092a53", width=1)
            draw.line([(512, r_y), (512, r_y + row_h)], fill="#092a53", width=1)

        name = item.get("name", "")
        qty = item.get("qty", 1)
        price = item.get("price", 0.0)
        line_total = item.get("total", qty * price)

        draw_center(draw, (c_prod, center_y), str(name), f_bold_md, fill="#111111")
        draw_center(draw, (c_qty, center_y), f"{qty:g}", f_reg_md, fill="#111111")
        draw_center(draw, (c_price, center_y), f"{price:,.2f}", f_reg_md, fill="#111111")
        draw_center(draw, (c_tot, center_y), f"{line_total:,.2f}", f_bold_md, fill="#111111")

    # 5. الإجماليات
    # نصوص المجموع الفرعي والضريبة فوق شريط الإجمالي
    tot_y = 590 + ((len(items) - 1) * row_h)
    draw_rtl(draw, (right_x, tot_y), f"المجموع الفرعي: {subtotal:,.2f}", f_bold_md, fill="#1a252f")
    tot_y += 28

    tax_str = f"{tax_rate * 100:.2f}%"
    draw_rtl(draw, (right_x, tot_y), f"الضريبة ({tax_str}): {subtotal * tax_rate:,.2f}", f_bold_md, fill="#1a252f")

    # شريط الإجمالي الكلي (المرسوم مسبقاً في القالب عند Y: 680 to 727)
    btn_center_y = (680 + 727) // 2 + ((len(items) - 1) * row_h)
    # إذا كان هناك صفوف إضافية حركت الموقع، نرسم شريط بديل
    if len(items) > 1:
        draw.rounded_rectangle([(42, btn_center_y - 24), (690, btn_center_y + 24)], radius=8, fill="#092a53")

    total_text = f"الإجمالي: {total:,.2f}"
    draw_center(draw, (366, btn_center_y), total_text, f_total_btn, fill="#ffb86c")

    # 6. الملاحظات (Y: 760)
    notes_y = 760 + ((len(items) - 1) * row_h)
    if notes:
        draw_rtl(draw, (right_x, notes_y), f"ملاحظات: {notes} 📝", f_bold_md, fill="#092a53")

    # 7. نصوص شريط الفوتر (عند Y: 985)
    footer_text_y = 988
    draw.text((45, footer_text_y - 7), "THANK YOU FOR YOUR TRUST 🧡", font=get_font(11, bold=True), fill="#FFFFFF")
    draw_rtl(draw, (right_x, footer_text_y), "VIP GAMING SERVICES 👑", get_font(11, bold=True), fill="#FFFFFF")

    return img

if __name__ == "__main__":
    out = render_on_user_template()
    out_file = OUTPUT_DIR / "new_template_result.png"
    out.save(str(out_file), quality=95)
    print(f"✅ Generated new template invoice at: {out_file}")
