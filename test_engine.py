"""
test_engine.py - اختبار محرك القوالب وتوليد الـ PDF والصور والنصوص
"""
import os
import sys
from pathlib import Path

# إضافة مسار المشروع
sys.path.insert(0, str(Path(__file__).parent))

from models import Invoice, Quote, Receipt, CustomerInfo, ProductItem, CustomTemplate, TemplateField, FilledTemplate
import template_engine as engine

def test_all():
    print("🚀 بدء اختبار محرك القوالب...")

    # 1. اختبار الفاتورة
    customer = CustomerInfo(name="أحمد محمد علي", phone="01012345678")
    items = [
        ProductItem(name="لابتوب ديل Core i7", quantity=1, unit_price=25000),
        ProductItem(name="ماوس لاسلكي لوجيتك", quantity=2, unit_price=750),
    ]
    inv = Invoice(
        customer=customer,
        items=items,
        tax_rate=0.14,
        notes="الضمان لمدة عام كامل",
        order_number="VIP-9942"
    )
    
    text_inv = engine.render_invoice_text(inv)
    assert "أحمد محمد علي" in text_inv
    print("✅ تم توليد نص الفاتورة بنجاح")

    img_inv = engine.render_invoice_image(inv)
    assert len(img_inv) > 1000
    print(f"✅ تم توليد صورة الفاتورة بنجاح ({len(img_inv)} بايت)")

    pdf_inv = engine.render_invoice_pdf(inv)
    assert len(pdf_inv) > 1000
    print(f"✅ تم توليد PDF الفاتورة بنجاح ({len(pdf_inv)} بايت)")

    # 2. اختبار عرض السعر
    quote = Quote(customer=customer, items=items, validity_days=15, terms="الدفع 50% مقدماً والباقي عند الاستلام")
    text_qt = engine.render_quote_text(quote)
    img_qt = engine.render_quote_image(quote)
    pdf_qt = engine.render_quote_pdf(quote)
    assert len(text_qt) > 50 and len(img_qt) > 1000 and len(pdf_qt) > 1000
    print("✅ تم توليد عرض السعر (نص + صورة + PDF) بنجاح")

    # 3. اختبار الإيصال
    receipt = Receipt(customer=customer, amount=15000, payment_method="فودافون كاش", description="دفعة أولى حجز أجهزة")
    text_rcp = engine.render_receipt_text(receipt)
    img_rcp = engine.render_receipt_image(receipt)
    pdf_rcp = engine.render_receipt_pdf(receipt)
    assert len(text_rcp) > 50 and len(img_rcp) > 1000 and len(pdf_rcp) > 1000
    print("✅ تم توليد إيصال الاستلام (نص + صورة + PDF) بنجاح")

    # 4. اختبار القوالب المخصصة
    custom_tpl = CustomTemplate(
        name="سند استلام بضاعة",
        fields=[
            TemplateField(name="اسم السائق"),
            TemplateField(name="رقم اللوحة"),
            TemplateField(name="المدينة"),
        ]
    )
    filled = FilledTemplate(
        template=custom_tpl,
        values={"اسم السائق": "محمود إبراهيم", "رقم اللوحة": "س ج ص 123", "المدينة": "الإسكندرية"}
    )
    text_c = engine.render_custom_template_text(filled)
    img_c = engine.render_custom_template_image(filled)
    pdf_c = engine.render_custom_template_pdf(filled)
    assert len(text_c) > 50 and len(img_c) > 1000 and len(pdf_c) > 1000
    print("✅ تم توليد القالب المخصص (نص + صورة + PDF) بنجاح")

    print("\n🎉 جميع الاختبارات نجحت 100%!")

if __name__ == "__main__":
    test_all()
