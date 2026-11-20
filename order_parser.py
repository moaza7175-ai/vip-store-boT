"""
order_parser.py - محلل ذكي لنصوص ورسائل الطلبات وشحن الألعاب
Smart parser for VIP STORE – GAMING SERVICES
Extracts: Order ID, Customer Name, Account Name, Player ID, Package/Product, Qty, Unit Price, Total, Date, Notes.
"""

import re
from datetime import datetime
from typing import Optional
from models import Invoice, CustomerInfo, ProductItem

def clean_marketing_noise(text: str) -> str:
    """تنظيف الرسالة من النصوص التسويقية والروابط ورسائل التقييم"""
    lines = []
    for line in text.splitlines():
        line_clean = line.strip()
        # تجاهل الروابط تماماً
        if re.search(r'https?://', line_clean):
            continue
        # تجاهل عبارات التقييم والشكر ومجموعات الفيسبوك والـ Trustpilot
        if any(w in line_clean.lower() for w in [
            "trustpilot", "facebook", "صفحتنا", "تقييمك", "رايك يهمنا", "رأيك يهمنا",
            "انضم الى", "جروب", "group", "تقييم الخدمة", "شكرا لاختيارك", "شكراً لاختيارك",
            "يسعدنا دائما", "نتمنى لك يوما", "مبروك عليك", "تم الشحن بنجاح"
        ]):
            continue
        lines.append(line_clean)
    return "\n".join(lines)


def extract_phone(text: str) -> str:
    """استخراج رقم الهاتف"""
    m = re.search(r'(?:الهاتف|تليفون|موبايل|رقم\s*الهاتف|phone|mobile)\s*[:=\-]?\s*([+0-9\s\-]{9,16})', text, re.IGNORECASE)
    if m:
        cleaned = re.sub(r'[\s\-]', '', m.group(1))
        if len(cleaned) >= 9:
            return cleaned

    phones = re.findall(r'(?:\+?20|0020)?0?(1[0125][0-9]{8})', text)
    if phones:
        return "0" + phones[0] if not phones[0].startswith("0") else phones[0]

    generic = re.findall(r'(?:\+|00)?[0-9]{9,14}', text)
    if generic:
        return generic[0]

    return ""


def is_order_message(text: str) -> bool:
    """
    فحص ذكي ودقيق: هل الرسالة عبارة عن رسالة طلب أو شحن حقيقية؟
    يمنع تماماً التعرف على الرسائل العادية أو الدردشة على أنها فواتير.
    """
    if not text or len(text.strip()) < 6:
        return False

    clean = text.strip()

    # 1. وجود كود أو رقم طلب صريح
    if re.search(r'(?:رقم\s*الطلب|كود\s*الطلب|معرف\s*الطلب|order\s*(?:id|num|no|#))\s*[:=\-]?\s*#?[A-Za-z0-9\-_]{2,}', clean, re.IGNORECASE):
        return True
    if re.search(r'\b(?:VIP|ORD|INV)-[A-Za-z0-9\-_]{3,}\b', clean, re.IGNORECASE):
        return True
    if re.search(r'#(?:VIP|ORD|INV)[A-Za-z0-9\-_]{2,}', clean, re.IGNORECASE):
        return True

    # 2. فحص المؤشرات المركبة:
    has_gaming = bool(re.search(r'(?:شحن|باقة|الباقة|المنتج|bonus|uc|شدات|جواهر|كوينز|حساب|ألعاب|العاب|pubg|free\s*fire|ببجي|فري\s*فاير)', clean, re.IGNORECASE))
    has_player_id = bool(re.search(r'(?:player\s*id|user\s*id|uid|id\s*الحساب|معرف\s*اللاعب|\bid\b\s*[:=\-]?\s*\d{5,})', clean, re.IGNORECASE))
    has_financials = bool(re.search(r'(?:التكلفة|تكلفة|سعر\s*الشراء|الأرباح|ارباح|الربح|صافي\s*الربح|الخسائر|خسارة|الإجمالي|اجمالي|المبلغ|الحساب|سعر\s*الوحدة)\s*[:=\-]?\s*[+\-]?\s*\d+', clean, re.IGNORECASE))

    if (has_gaming or has_player_id) and has_financials:
        return True

    # 3. نمط القائمة المهيكلة (وجود حقلين على الأقل من حقول الفواتير متبوعة بـ نقطتين رأسيتين وقيمة)
    fields_count = 0
    structured_patterns = [
        r'(?:الطلب|order)\s*[:=\-]\s*.+',
        r'(?:التاريخ|date)\s*[:=\-]\s*.+',
        r'(?:العميل|customer)\s*[:=\-]\s*.+',
        r'(?:الحساب|account)\s*[:=\-]\s*.+',
        r'(?:id|uid|معرف)\s*[:=\-]\s*\d+',
        r'(?:الباقة|المنتج|package|product)\s*[:=\-]\s*.+',
        r'(?:الكمية|qty)\s*[:=\-]\s*\d+',
        r'(?:التكلفة|cost)\s*[:=\-]\s*\d+',
        r'(?:الأرباح|profit)\s*[:=\-]\s*[+\-]?\d+',
        r'(?:الخسائر|losses)\s*[:=\-]\s*\d+',
        r'(?:الإجمالي|total)\s*[:=\-]\s*\d+',
    ]
    for p in structured_patterns:
        if re.search(p, clean, re.IGNORECASE):
            fields_count += 1

    if fields_count >= 2:
        return True

    return False


def extract_order_number(text: str) -> str:
    """استخراج رقم أو كود الطلب (مع عدم الخلط بينه وبين Player ID أو الكلمات العادية)"""
    # 1. البحث بالكلمات الدلالية الصريحة لرقم الطلب فقط
    m = re.search(r'(?:رقم\s*الطلب|كود\s*الطلب|معرف\s*الطلب|order\s*(?:id|num|no|#)?)\s*[:=\-]?\s*#?([A-Za-z0-9\-_]{2,30})', text, re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        if not re.match(r'^(?:جديد|قديم|شحن|فوري|اونلاين|الكتروني|مهم|عاجل|شراء)$', val):
            return val

    # 2. البحث عن كود صريح يبدأ بـ VIP- أو ORD- أو INV-
    m_pref = re.search(r'\b((?:VIP|ORD|INV)[A-Za-z0-9\-_]{3,20})\b', text, re.IGNORECASE)
    if m_pref:
        return m_pref.group(1).strip()

    # 3. البحث عن نمط #VIP-123 أو #1234
    m_hash = re.search(r'#([A-Za-z0-9\-_]{3,25})', text)
    if m_hash:
        val = m_hash.group(1).strip()
        if not re.match(r'^(?:جديد|قديم|شحن|فوري|اونلاين|الكتروني|مهم|عاجل|شراء)$', val):
            return val

    return ""


def extract_player_id(text: str) -> str:
    """استخراج ID الحساب داخل اللعبة (Player ID) بدقة وبشكل منفصل عن رقم الطلب"""
    # البحث عن كلمات دلالية صريحة للـ Player ID
    patterns = [
        r'(?:ID\s*الحساب|معرف\s*اللاعب|ID\s*اللاعب|رقم\s*الحساب|آي\s*دي|ايدي|player\s*id|user\s*id|uid|account\s*id)\s*[:=\-]?\s*([0-9]{5,16})',
        r'\b(?:ID|UID)\s*[:=\-]?\s*([0-9]{5,16})\b',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def extract_account_name(text: str) -> str:
    """استخراج اسم الحساب داخل اللعبة (In-Game Name / Nickname)"""
    patterns = [
        r'(?:اسم\s*الحساب|اسم\s*اللاعب|اسم\s*الأكونت|النيك\s*نيم|account\s*name|in-?game\s*name|ign|nickname|gamer\s*tag)\s*[:=\-]?\s*([^\n\r,;|]+)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            val = re.sub(r'^[^\w\s]+|[^\w\s]+$', '', val).strip()
            if val and len(val) >= 2:
                return val
    return ""


def extract_customer_name(text: str, account_name: str = "") -> str:
    """
    استخراج اسم العميل فقط
    قاعدة صارمة: لا يعتبر اسم العميل هو اسم الحساب إلا إذا كانا متطابقين في الرسالة.
    إذا لم يُذكر اسم العميل، نرجع نصاً فارغاً ولا نخمنه من اسم الحساب.
    """
    # 1. البحث الصريح عن اسم العميل
    m = re.search(r'(?:اسم\s*العميل|العميل|المشتري|customer\s*name|client)\s*[:=\-]?\s*([^\n\r,;|]+)', text, re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        name = re.sub(r'^[^\w\s]+|[^\w\s]+$', '', name).strip()
        if name and len(name) >= 2:
            return name

    # 2. البحث عن 'الاسم:' بشرط ألا يكون 'اسم الحساب'
    for line in text.splitlines():
        line_s = line.strip()
        if re.search(r'اسم\s*الحساب|account\s*name', line_s, re.IGNORECASE):
            continue
        m_simple = re.search(r'^(?:الاسم|اسم)\s*[:=\-]?\s*([^\n\r,;|]+)', line_s, re.IGNORECASE)
        if m_simple:
            name = m_simple.group(1).strip()
            name = re.sub(r'^[^\w\s]+|[^\w\s]+$', '', name).strip()
            if name and len(name) >= 2 and name != account_name:
                return name

    # إذا لم يذكر اسم العميل لا نخمن ولا نرجع اسم الحساب
    return ""


def extract_order_date(text: str) -> str:
    """استخراج تاريخ الطلب كما ورد في الرسالة، أو التاريخ الحالي إن لم يوجد"""
    # البحث عن تاريخ بنمط YYYY-MM-DD أو DD-MM-YYYY
    m = re.search(r'(?:تاريخ\s*الطلب|التاريخ|date)\s*[:=\-]?\s*([0-9]{1,4}[-/.][0-9]{1,2}[-/.][0-9]{1,4}(?:\s+[0-9]{1,2}:[0-9]{2})?)', text, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    m_date_standalone = re.search(r'\b([0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{2,4}(?:\s+[0-9]{1,2}:[0-9]{2})?)\b', text)
    if m_date_standalone:
        return m_date_standalone.group(1).strip()

    return datetime.now().strftime("%Y-%m-%d %H:%M")


def extract_notes(text: str) -> str:
    """استخراج الملاحظات إن وجدت"""
    m = re.search(r'(?:ملاحظات|ملاحظة|notes?)\s*[:=\-]?\s*([^\n\r]+)', text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""


def extract_tax(text: str) -> float:
    """استخراج نسبة الضريبة إن وجدت"""
    m = re.search(r'(?:ضريبة|الضريبة|tax)\s*[:=\-]?\s*([0-9.]+)\s*%?', text, re.IGNORECASE)
    if m:
        try:
            val = float(m.group(1))
            return val / 100.0 if val > 1.0 else val
        except ValueError:
            pass
    return 0.0


def parse_items(text: str) -> list[ProductItem]:
    """استخراج قائمة المنتجات والكميات والأسعار مع مراعاة قواعد عدم تخمين الأسعار"""
    items: list[ProductItem] = []
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]

    # فحص أسطر المنتجات المفصولة
    for line in lines:
        if any(re.search(pat, line, re.IGNORECASE) for pat in [
            r'^(?:الاسم|اسم\s*العميل|اسم\s*الحساب|الهاتف|تليفون|موبايل|رقم\s*الطلب|كود|التاريخ|ملاحظات|id|player)',
        ]):
            continue

        # نمط A: اسم | كمية | سعر أو اسم - كمية - سعر
        m_sep = re.match(r'^([^|\-,]+?)\s*[|\-,]\s*(\d+(?:\.\d+)?)\s*[|\-,]\s*(\d+(?:\.\d+)?)\s*(?:ج|جنيه|ريال|\$|EGP|SAR)?$', line)
        if m_sep:
            name = m_sep.group(1).strip()
            qty = float(m_sep.group(2))
            price = float(m_sep.group(3))
            if qty > 0 and price >= 0 and len(name) >= 2:
                items.append(ProductItem(name=name, quantity=qty, unit_price=price))
                continue

        # نمط B: اسم x كمية = إجمالي
        m_x = re.search(r'^(.+?)\s*(?:[xX*×])\s*(\d+(?:\.\d+)?)\s*(?:[=@]\s*(\d+(?:\.\d+)?))?', line)
        if m_x:
            name = m_x.group(1).strip()
            qty = float(m_x.group(2))
            total_or_price = float(m_x.group(3)) if m_x.group(3) else 0.0
            unit_price = (total_or_price / qty) if (total_or_price > 0 and qty > 0) else total_or_price
            if len(name) >= 2 and qty > 0:
                items.append(ProductItem(name=name, quantity=qty, unit_price=unit_price))
                continue

        # نمط C: اسم السلعة ثم سعر ثم عدد
        m_count = re.search(r'^(.+?)\s+(\d+(?:\.\d+)?)\s*(?:ج|جنيه|ريال|\$|EGP)?\s+(?:عدد|كمية|قطع)?\s*(\d+)', line)
        if m_count:
            name = m_count.group(1).strip()
            price = float(m_count.group(2))
            qty = float(m_count.group(3))
            if len(name) >= 2:
                items.append(ProductItem(name=name, quantity=qty, unit_price=price))
                continue

    if items:
        return items

    # فحص الكلمات الدلالية في كامل النص (المنتج / الباقة / الكمية / السعر)
    p_name = ""
    p_qty = 1.0
    p_price = 0.0

    m_pname = re.search(r'(?:المنتج|الباقة|الصنف|البند|item|product|package)\s*[:=\-]?\s*([^\n\r]+)', text, re.IGNORECASE)
    if m_pname:
        p_name = m_pname.group(1).strip()

    m_pqty = re.search(r'(?:الكمية|العدد|عدد|qty|count)\s*[:=\-]?\s*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
    if m_pqty:
        try:
            p_qty = float(m_pqty.group(1))
        except ValueError:
            p_qty = 1.0

    m_pprice = re.search(r'(?:سعر\s*الوحدة|السعر|price|cost)\s*[:=\-]?\s*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
    if m_pprice:
        try:
            p_price = float(m_pprice.group(1))
        except ValueError:
            p_price = 0.0
    else:
        # البحث عن الإجمالي
        m_ptot = re.search(r'(?:الإجمالي|المجموع|المبلغ|الحساب|total)\s*[:=\-]?\s*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
        if m_ptot:
            try:
                tot = float(m_ptot.group(1))
                p_price = tot / p_qty if p_qty > 0 else tot
            except ValueError:
                p_price = 0.0

    if p_name:
        items.append(ProductItem(name=p_name, quantity=p_qty, unit_price=p_price))
        return items

    # محاولة أخيرة: البحث عن سطر يحتوي على اسم وسعر
    for line in lines:
        if any(re.search(pat, line, re.IGNORECASE) for pat in [
            r'^(?:الاسم|اسم\s*العميل|اسم\s*الحساب|الهاتف|تليفون|موبايل|رقم\s*الطلب|كود|التاريخ|ملاحظات|id|player)',
        ]):
            continue
        m_simple = re.search(r'^(.+?)\s+(\d+(?:\.\d+)?)\s*(?:ج|جنيه|ريال|\$|EGP)?$', line)
        if m_simple:
            name = m_simple.group(1).strip()
            price = float(m_simple.group(2))
            if len(name) >= 3 and not name.isdigit():
                items.append(ProductItem(name=name, quantity=1.0, unit_price=price))

    return items


def parse_order_text(text: str) -> Optional[Invoice]:
    """
    تحليل الرسالة واستخراج كافة بيانات الفاتورة المحددة في قواعد VIP STORE
    """
    if not text or len(text.strip()) < 5:
        return None

    # تنظيف الرسالة من النصوص التسويقية وروابط التقييم
    clean_text = clean_marketing_noise(text)

    order_num = extract_order_number(clean_text)
    player_id = extract_player_id(clean_text)
    account_name = extract_account_name(clean_text)
    cust_name = extract_customer_name(clean_text, account_name=account_name)
    cust_phone = extract_phone(clean_text)
    items = parse_items(clean_text)
    notes = extract_notes(clean_text)
    tax_rate = extract_tax(clean_text)
    date_val = extract_order_date(clean_text)

    # التحقق من وجود بيانات طلب حقيقية
    if not items and not order_num and not player_id:
        return None

    # إذا لم توجد بنود محددة، نضع بند باقة الألعاب المشحونة
    if not items:
        m_tot = re.search(r'(?:الإجمالي|المجموع|المبلغ|الحساب|total)\s*[:=\-]?\s*(\d+(?:\.\d+)?)', clean_text, re.IGNORECASE)
        tot_val = float(m_tot.group(1)) if m_tot else 0.0
        items.append(ProductItem(name="شحن خدمات ألعاب", quantity=1.0, unit_price=tot_val))

    customer = CustomerInfo(name=cust_name, phone=cust_phone)
    invoice = Invoice(
        customer=customer,
        items=items,
        tax_rate=tax_rate,
        notes=notes,
        order_number=order_num,
        account_name=account_name,
        player_id=player_id,
        date=date_val,
        doc_type="فاتورة VIP STORE",
    )
    return invoice


def extract_financials_from_text(text: str) -> dict:
    """استخراج بيانات التكلفة والمصروفات والخسائر إن وجدت مسبقاً في رسالة الطلب"""
    cost, exp, losses = 0.0, 0.0, 0.0
    has_cost = False

    m_cost = re.search(r'(?:التكلفة|تكلفة|شراء|سعر\s*الشراء|cost)\s*[:=\-]?\s*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
    if m_cost:
        cost = float(m_cost.group(1))
        has_cost = True

    m_exp = re.search(r'(?:المصروفات|مصروفات|مصاريف|عمولة|expenses?)\s*[:=\-]?\s*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
    if m_exp:
        exp = float(m_exp.group(1))

    m_loss = re.search(r'(?:الخسائر|خسائر|خسارة|losses?)\s*[:=\-]?\s*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
    if m_loss:
        losses = float(m_loss.group(1))

    return {"has_cost": has_cost, "cost": cost, "expenses": exp, "losses": losses}


def parse_financial_input(text: str) -> tuple[float, float, float]:
    """
    تحليل رد المستخدم عند طلب التكلفة والمصروفات والخسائر
    يدعم:
    - رقم واحد: '250' -> (250, 0, 0)
    - رقمين: '250 5' -> (250, 5, 0)
    - 3 أرقام: '250 5 10' -> (250, 5, 10)
    - نصوص مسماة: 'التكلفة: 250 المصروفات: 5 الخسائر: 0'
    """
    cleaned = text.strip()
    fin = extract_financials_from_text(cleaned)
    if fin["has_cost"]:
        return fin["cost"], fin["expenses"], fin["losses"]

    nums = re.findall(r'\b\d+(?:\.\d+)?\b', cleaned)
    if nums:
        cost = float(nums[0])
        exp = float(nums[1]) if len(nums) > 1 else 0.0
        losses = float(nums[2]) if len(nums) > 2 else 0.0
        return cost, exp, losses

    return 0.0, 0.0, 0.0


def inspect_missing_data(raw_text: str) -> dict:
    """
    VIP STORE – Smart Missing Data Assistant
    يفحص الرسالة ويستخرج كافة البيانات المتاحة، ثم يقارنها بالحقول الـ 11:
    - رقم الطلب
    - التاريخ
    - اسم العميل
    - اسم الحساب
    - ID الحساب
    - اسم المنتج أو الباقة
    - الكمية
    - التكلفة
    - الأرباح
    - الخسائر
    - الإجمالي أو الإيرادات
    """
    clean = clean_marketing_noise(raw_text)

    # 1. رقم الطلب
    order_num = extract_order_number(clean)

    # 2. التاريخ
    m_date = re.search(r'(?:تاريخ\s*الطلب|التاريخ|date)\s*[:=\-]?\s*([^\n\r]+)', clean, re.IGNORECASE)
    if m_date:
        date_val = m_date.group(1).strip()
    else:
        m_dt = re.search(r'\b([0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{2,4}(?:\s+[0-9]{1,2}:[0-9]{2})?)\b', clean)
        date_val = m_dt.group(1).strip() if m_dt else None

    # 4. اسم الحساب داخل اللعبة (مفصول تماماً ومستقل عن اسم العميل)
    acc_name = extract_account_name(clean)
    if not acc_name:
        acc_name = None

    # 3. اسم العميل (مفصول تماماً ولا يعتبر اسم الحساب إلا إذا ذُكر صراحة)
    cust_name = extract_customer_name(clean, account_name=acc_name or "")
    if not cust_name:
        cust_name = None

    cust_phone = extract_phone(clean)

    # 5. ID الحساب
    m_pid = re.search(r'(?:id\s*الحساب|id\s*اللاعب|player\s*id|user\s*id|\bid\b)\s*[:=\-]?\s*([0-9]{5,15})', clean, re.IGNORECASE)
    player_id = m_pid.group(1).strip() if m_pid else None

    # 6. الباقة / المنتج
    m_prod = re.search(r'(?:الباقة|المنتج|الصنف|البند|package|product|item)\s*[:=\-]?\s*([^\n\r]+)', clean, re.IGNORECASE)
    prod_name = m_prod.group(1).strip() if m_prod else None

    # 7. الكمية
    m_qty = re.search(r'(?:الكمية|العدد|عدد|qty|count)\s*[:=\-]?\s*(\d+(?:\.\d+)?)', clean, re.IGNORECASE)
    qty_val = float(m_qty.group(1)) if m_qty else None

    # 8. التكلفة
    m_cost = re.search(r'(?:التكلفة|تكلفة|سعر\s*الشراء|شراء|cost)\s*[:=\-]?\s*(\d+(?:\.\d+)?)', clean, re.IGNORECASE)
    cost_val = float(m_cost.group(1)) if m_cost else None

    # 9. الأرباح
    m_profit = re.search(r'(?:الأرباح|الربح|أرباح|صافي\s*الربح|profit)\s*[:=\-]?\s*([+\-]?\s*\d+(?:\.\d+)?)', clean, re.IGNORECASE)
    profit_val = float(re.sub(r'\s+', '', m_profit.group(1))) if m_profit else None

    # 10. الخسائر
    m_loss = re.search(r'(?:الخسائر|الخسارة|خسائر|خسارة|losses?)\s*[:=\-]?\s*(\d+(?:\.\d+)?)', clean, re.IGNORECASE)
    loss_val = float(m_loss.group(1)) if m_loss else None

    # 11. الإجمالي
    m_tot = re.search(r'(?:الإجمالي|المجموع|الإيرادات|المبلغ|الحساب|total|revenue)\s*[:=\-]?\s*(\d+(?:\.\d+)?)', clean, re.IGNORECASE)
    total_val = float(m_tot.group(1)) if m_tot else None

    # استكمال من جدول البنود إذا لم تكن الباقة مستخرجة صراحة
    if not prod_name:
        items = parse_items(clean)
        if items:
            prod_name = items[0].name
            if qty_val is None and re.search(r'(?:x|\*|×|\bالكمية\b|\bعدد\b)', clean):
                qty_val = items[0].quantity
            if total_val is None and items[0].total > 0:
                total_val = items[0].total

    # حساب العلاقات المتبادلة للأرقام المالية دون تعديل ما أرسله المستخدم
    if total_val is not None and cost_val is not None and profit_val is None:
        profit_val = total_val - cost_val - (loss_val or 0.0)
    elif cost_val is not None and profit_val is not None and total_val is None:
        total_val = cost_val + profit_val + (loss_val or 0.0)
    elif total_val is not None and profit_val is not None and cost_val is None:
        cost_val = total_val - profit_val - (loss_val or 0.0)

    # تجهيز الحقول الـ 11 بالترتيب
    fields_spec = [
        ("order_number", "رقم الطلب", order_num, f"#{order_num}" if order_num else ""),
        ("date", "التاريخ", date_val, str(date_val) if date_val else ""),
        ("customer_name", "اسم العميل", cust_name, str(cust_name) if cust_name else ""),
        ("account_name", "اسم الحساب", acc_name, str(acc_name) if acc_name else ""),
        ("player_id", "ID الحساب", player_id, str(player_id) if player_id else ""),
        ("product_name", "الباقة", prod_name, str(prod_name) if prod_name else ""),
        ("quantity", "الكمية", qty_val, f"{qty_val:g}" if qty_val is not None else ""),
        ("cost", "التكلفة", cost_val, f"{cost_val:,.2f} جنيه" if cost_val is not None else ""),
        ("profit", "الأرباح", profit_val, f"{profit_val:+,.2f} جنيه" if profit_val is not None else ""),
        ("losses", "الخسائر", loss_val, f"{loss_val:,.2f} جنيه" if loss_val is not None else ""),
        ("total_amount", "الإجمالي", total_val, f"{total_val:,.2f} جنيه" if total_val is not None else ""),
    ]

    available = []
    missing = []

    for key, label, val, formatted_val in fields_spec:
        if val is not None and str(val).strip() != "":
            available.append({"key": key, "label": label, "val": formatted_val})
        else:
            missing.append({"key": key, "label": label})

    # تجهيز كائن الطلب الكامل
    order_data = {
        "order_number": order_num or "",
        "date": date_val or datetime.now().strftime("%Y-%m-%d %H:%M"),
        "customer_name": cust_name or "",
        "customer_phone": cust_phone or "",
        "account_name": acc_name or "",
        "player_id": player_id or "",
        "product_name": prod_name or "شحن ألعاب",
        "quantity": qty_val if qty_val is not None else 1.0,
        "cost": cost_val if cost_val is not None else 0.0,
        "profit": profit_val if profit_val is not None else 0.0,
        "losses": loss_val if loss_val is not None else 0.0,
        "expenses": 0.0,
        "total_amount": total_val if total_val is not None else ((cost_val or 0.0) + (profit_val or 0.0)),
        "notes": extract_notes(clean),
        "status": "draft",
    }
    
    # حساب صافي الربح
    order_data["net_profit"] = order_data["profit"] if profit_val is not None else (order_data["total_amount"] - order_data["cost"] - order_data["losses"])
    order_data["items"] = [{"name": order_data["product_name"], "quantity": order_data["quantity"], "unit_price": (order_data["total_amount"] / order_data["quantity"]) if order_data["quantity"] > 0 else order_data["total_amount"], "total": order_data["total_amount"]}]

    return {
        "order_data": order_data,
        "available_fields": available,
        "missing_fields": missing,
        "raw_text": raw_text
    }


def update_order_with_text(order_data: dict, text: str) -> list[str]:
    """تحديث بيانات الطلب من رسالة نصية واسترجاع أسماء الحقول التي تم تحديثها"""
    updated = []
    clean = clean_marketing_noise(text)

    # رقم الطلب
    m_ord = re.search(r'(?:رقم\s*الطلب|كود\s*الطلب|order\s*(?:id|num|no)?)\s*[:=\-]?\s*#?([A-Za-z0-9\-_]+)', clean, re.IGNORECASE)
    if m_ord:
        val = m_ord.group(1).strip()
        if val and len(val) >= 2 and not re.match(r'^(?:جديد|قديم|شحن|فوري|اونلاين)$', val):
            order_data["order_number"] = val
            updated.append("رقم الطلب")

    # اسم العميل
    m_cust = re.search(r'(?:اسم\s*العميل|العميل|الاسم|customer\s*name)\s*[:=\-]?\s*([^\n\r]+)', clean, re.IGNORECASE)
    if m_cust:
        val = m_cust.group(1).strip()
        if val:
            order_data["customer_name"] = val
            updated.append("اسم العميل")

    # الهاتف
    m_phone = re.search(r'(?:الهاتف|تليفون|موبايل|phone|mobile)\s*[:=\-]?\s*([+0-9\s\-]{9,16})', clean, re.IGNORECASE)
    if m_phone:
        cleaned_ph = re.sub(r'[\s\-]', '', m_phone.group(1))
        order_data["customer_phone"] = cleaned_ph
        updated.append("الهاتف")

    # اسم الحساب
    m_acc = re.search(r'(?:اسم\s*الحساب|الحساب|account\s*name)\s*[:=\-]?\s*([^\n\r]+)', clean, re.IGNORECASE)
    if m_acc:
        val = m_acc.group(1).strip()
        if val:
            order_data["account_name"] = val
            updated.append("اسم الحساب")

    # ID الحساب
    m_pid = re.search(r'(?:id\s*الحساب|id\s*اللاعب|player\s*id|\bid\b)\s*[:=\-]?\s*([0-9]{5,15})', clean, re.IGNORECASE)
    if m_pid:
        val = m_pid.group(1).strip()
        if val:
            order_data["player_id"] = val
            updated.append("ID الحساب")

    # الكمية
    m_qty = re.search(r'(?:الكمية|العدد|عدد|qty)\s*[:=\-]?\s*(\d+(?:\.\d+)?)', clean, re.IGNORECASE)
    if m_qty:
        try:
            val = float(m_qty.group(1))
            order_data["quantity"] = val
            if order_data.get("items"):
                order_data["items"][0]["quantity"] = val
            updated.append("الكمية")
        except ValueError:
            pass

    return updated


