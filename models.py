"""
models.py - نماذج البيانات
Data models for invoices, quotes, receipts, and custom templates
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
import uuid


@dataclass
class ProductItem:
    """عنصر منتج في الفاتورة أو عرض السعر"""
    name: str
    quantity: float
    unit_price: float

    @property
    def total(self) -> float:
        """إجمالي سعر المنتج"""
        return self.quantity * self.unit_price


@dataclass
class CustomerInfo:
    """بيانات العميل"""
    name: str
    phone: str = ""
    email: str = ""
    address: str = ""


@dataclass
class Invoice:
    """نموذج الفاتورة"""
    customer: CustomerInfo
    items: list[ProductItem] = field(default_factory=list)
    tax_rate: float = 0.0
    notes: str = ""
    invoice_number: str = ""
    order_number: str = ""
    account_name: str = ""
    player_id: str = ""
    date: str = ""
    doc_type: str = "فاتورة"

    def __post_init__(self):
        if not self.invoice_number:
            if self.order_number:
                self.invoice_number = f"INV-{self.order_number}"
            else:
                self.invoice_number = f"INV-{uuid.uuid4().hex[:8].upper()}"
        if not self.date:
            self.date = datetime.now().strftime("%Y-%m-%d %H:%M")

    @property
    def subtotal(self) -> float:
        """المجموع الفرعي قبل الضريبة"""
        return sum(item.total for item in self.items)

    @property
    def tax_amount(self) -> float:
        """قيمة الضريبة"""
        return self.subtotal * self.tax_rate

    @property
    def total(self) -> float:
        """الإجمالي شامل الضريبة"""
        return self.subtotal + self.tax_amount

    def to_dict(self) -> dict:
        """تحويل الفاتورة إلى قاموس لتخزينها في قاعدة البيانات"""
        return {
            "order_number": self.order_number,
            "invoice_number": self.invoice_number,
            "date": self.date,
            "customer_name": self.customer.name,
            "customer_phone": self.customer.phone,
            "account_name": self.account_name,
            "player_id": self.player_id,
            "items": [
                {
                    "name": it.name,
                    "quantity": it.quantity,
                    "unit_price": it.unit_price,
                    "total": it.total,
                }
                for it in self.items
            ],
            "subtotal": self.subtotal,
            "tax_rate": self.tax_rate,
            "tax_amount": self.tax_amount,
            "total_amount": self.total,
            "notes": self.notes,
            "doc_type": self.doc_type,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Invoice":
        """إنشاء كائن Invoice من قاموس بيانات الطلب"""
        cust_name = data.get("customer_name") or "عميل VIP STORE"
        cust_phone = data.get("customer_phone") or ""
        customer = CustomerInfo(name=cust_name, phone=cust_phone)

        raw_items = data.get("items", [])
        items = []
        if raw_items:
            for it in raw_items:
                if isinstance(it, dict):
                    name = it.get("name") or data.get("product_name") or "شحن ألعاب"
                    qty = float(it.get("quantity") or data.get("quantity") or 1.0)
                    price = float(it.get("unit_price") or (it.get("total", 0.0) / qty if qty > 0 and it.get("total") else 0.0))
                    items.append(ProductItem(name=name, quantity=qty, unit_price=price))
        if not items:
            name = data.get("product_name") or "شحن ألعاب"
            qty = float(data.get("quantity") or 1.0)
            tot = float(data.get("total_amount", 0.0) or data.get("total", 0.0) or 0.0)
            price = (tot / qty) if qty > 0 else tot
            items.append(ProductItem(name=name, quantity=qty, unit_price=price))

        return cls(
            customer=customer,
            items=items,
            tax_rate=float(data.get("tax_rate", 0.0)),
            notes=data.get("notes", ""),
            invoice_number=data.get("invoice_number", f"INV-{data.get('order_number', '')}"),
            order_number=data.get("order_number", ""),
            account_name=data.get("account_name", ""),
            player_id=data.get("player_id", ""),
            date=data.get("date", datetime.now().strftime("%Y-%m-%d %H:%M")),
            doc_type=data.get("doc_type", "فاتورة"),
        )


@dataclass
class Quote:
    """نموذج عرض السعر"""
    customer: CustomerInfo
    items: list[ProductItem] = field(default_factory=list)
    validity_days: int = 30
    terms: str = ""
    notes: str = ""
    quote_number: str = ""
    date: str = ""
    doc_type: str = "عرض سعر"

    def __post_init__(self):
        if not self.quote_number:
            self.quote_number = f"QT-{uuid.uuid4().hex[:8].upper()}"
        if not self.date:
            self.date = datetime.now().strftime("%Y-%m-%d %H:%M")

    @property
    def expiry_date(self) -> str:
        """تاريخ انتهاء الصلاحية"""
        expiry = datetime.now() + timedelta(days=self.validity_days)
        return expiry.strftime("%Y-%m-%d")

    @property
    def subtotal(self) -> float:
        """المجموع الفرعي"""
        return sum(item.total for item in self.items)

    @property
    def total(self) -> float:
        """الإجمالي"""
        return self.subtotal


@dataclass
class Receipt:
    """نموذج إيصال الاستلام"""
    customer: CustomerInfo
    amount: float = 0.0
    payment_method: str = ""
    description: str = ""
    notes: str = ""
    receipt_number: str = ""
    date: str = ""
    doc_type: str = "إيصال استلام"

    def __post_init__(self):
        if not self.receipt_number:
            self.receipt_number = f"RCP-{uuid.uuid4().hex[:8].upper()}"
        if not self.date:
            self.date = datetime.now().strftime("%Y-%m-%d %H:%M")


@dataclass
class TemplateField:
    """حقل في قالب مخصص"""
    name: str
    field_type: str = "text"  # text, number, date
    required: bool = True


@dataclass
class CustomTemplate:
    """قالب مخصص"""
    name: str
    fields: list[TemplateField] = field(default_factory=list)
    template_id: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.template_id:
            self.template_id = f"TPL-{uuid.uuid4().hex[:8].upper()}"
        if not self.created_at:
            self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    def to_dict(self) -> dict:
        """تحويل القالب إلى قاموس"""
        return {
            "name": self.name,
            "template_id": self.template_id,
            "created_at": self.created_at,
            "fields": [
                {
                    "name": f.name,
                    "field_type": f.field_type,
                    "required": f.required,
                }
                for f in self.fields
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CustomTemplate":
        """إنشاء قالب من قاموس"""
        fields = [
            TemplateField(
                name=f["name"],
                field_type=f.get("field_type", "text"),
                required=f.get("required", True),
            )
            for f in data.get("fields", [])
        ]
        return cls(
            name=data["name"],
            fields=fields,
            template_id=data.get("template_id", ""),
            created_at=data.get("created_at", ""),
        )


@dataclass
class FilledTemplate:
    """قالب مخصص تم تعبئته بالبيانات"""
    template: CustomTemplate
    values: dict = field(default_factory=dict)
    doc_number: str = ""
    date: str = ""
    doc_type: str = "مستند مخصص"

    def __post_init__(self):
        if not self.doc_number:
            self.doc_number = f"DOC-{uuid.uuid4().hex[:8].upper()}"
        if not self.date:
            self.date = datetime.now().strftime("%Y-%m-%d %H:%M")
