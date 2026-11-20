"""
test_vip_store.py - اختبار شامل لنظام VIP STORE - Smart Invoice Generator
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from order_parser import parse_order_text
import template_engine as engine
from config import OUTPUT_DIR

def test_vip_flow():
    print("🚀 بدء اختبار مولد فواتير VIP STORE...")

    # رسالة طلب نموذجية تحتوي على كلام تسويقي وروابط وبيانات اللعبة
    sample_order_msg = """
    تم استلام طلبك بنجاح في متجر VIP STORE!
    شكراً لاختيارك متجرنا ونتمنى لك تجربة لعب ممتعة 🎮
    https://trustpilot.com/review/vipstore.com
    
    رقم الطلب: VIPDHJFDKJMH
    تاريخ الطلب: 20-11-2026 03:32
    اسم العميل: MOAZ AMR
    الهاتف: 01062318668
    اسم الحساب: VIP_SNIPER
    Player ID: 512398741
    
    تفاصيل الباقة:
    المنتج: 325 BONUS
    الكمية: 3
    السعر: 300
    الإجمالي: 900
    
    ملاحظات: شحن فوري عن طريق الـ ID
    
    انضم لجروبنا على الفيسبوك: https://facebook.com/groups/vipstore
    رأيك يهمنا في تقييم الخدمة ⭐⭐⭐⭐⭐
    """

    # 1. اختبار استخراج البيانات الذكي
    invoice = parse_order_text(sample_order_msg)
    assert invoice is not None, "فشل استخراج بيانات الفاتورة!"
    
    print("✅ تم استخراج البيانات بنجاح:")
    print(f"  • رقم الطلب: {invoice.order_number}")
    print(f"  • اسم العميل: {invoice.customer.name}")
    print(f"  • الهاتف: {invoice.customer.phone}")
    print(f"  • اسم الحساب: {invoice.account_name}")
    print(f"  • Player ID: {invoice.player_id}")
    print(f"  • التاريخ: {invoice.date}")
    print(f"  • عدد المنتجات: {len(invoice.items)}")
    print(f"  • الإجمالي: {invoice.total}")
    print(f"  • الملاحظات: {invoice.notes}")

    assert invoice.order_number == "VIPDHJFDKJMH"
    assert invoice.player_id == "512398741"
    assert invoice.account_name == "VIP_SNIPER"
    assert invoice.customer.name == "MOAZ AMR"
    assert invoice.total == 900.0

    # 2. اختبار توليد الصورة عالية الجودة
    img_bytes = engine.render_invoice_image(invoice)
    assert len(img_bytes) > 50000
    img_file = OUTPUT_DIR / f"{invoice.order_number}.png"
    img_file.write_bytes(img_bytes)
    print(f"✅ تم توليد وحفظ صورة الفاتورة ({len(img_bytes)} بايت) في: {img_file}")

    # 3. اختبار توليد ملف PDF عالي الجودة باسم رقم الطلب
    pdf_bytes = engine.render_invoice_pdf(invoice)
    assert len(pdf_bytes) > 50000
    pdf_file = OUTPUT_DIR / f"{invoice.order_number}.pdf"
    pdf_file.write_bytes(pdf_bytes)
    print(f"✅ تم توليد وحفظ ملف الـ PDF ({len(pdf_bytes)} بايت) في: {pdf_file}")

    print("\n🎉 جميع اختبارات VIP STORE نجحت 100% بدون أي أخطاء!")

if __name__ == "__main__":
    test_vip_flow()
