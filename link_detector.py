"""
link_detector.py - كاشف ومحلل الروابط لنظام VIP STORE LINK BRIDGE
Extracts, validates, deduplicates, and orders URLs from incoming messages.
Supports Midasbuy, Web, Social Media, Telegram, Product, Order & Media Links.
"""

import re
import uuid
import time
import hashlib
from typing import List, Dict, Optional, Tuple


# نمط متقدم وشامل للتعرف على مختلف أنواع الروابط
URL_PATTERN = re.compile(
    r'(?:https?://|www\.|t\.me/|tg://)(?:[a-zA-Z0-9_\-\.~!$&\'()*+,;=:@%]+'
    r'(?::\d+)?(?:/[a-zA-Z0-9_\-\.~!$&\'()*+,;=:@%/?#]*)*)',
    re.IGNORECASE
)


class LinkDeduplicator:
    """نظام منع تكرار تحويل نفس الرابط أو الرسالة خلال فترة زمنية محددة"""
    def __init__(self, cache_ttl_seconds: int = 300):
        self.cache_ttl = cache_ttl_seconds
        self._seen: Dict[str, float] = {}

    def is_duplicate(self, text_or_link: str, user_id: int) -> bool:
        """فحص ما إذا كان الرابط مكرراً لنفس المستخدم"""
        now = time.time()
        self._cleanup(now)

        key = hashlib.sha256(f"{user_id}:{text_or_link.strip()}".encode()).hexdigest()
        if key in self._seen:
            return True

        self._seen[key] = now
        return False

    def _cleanup(self, now: float):
        """تنظيف السجلات القديمة تلقائياً"""
        expired = [k for k, timestamp in self._seen.items() if now - timestamp > self.cache_ttl]
        for k in expired:
            del self._seen[k]


# كائن مانع التكرار العام
deduplicator = LinkDeduplicator()


def generate_transaction_id() -> str:
    """توليد معرف عملية فريد واحترافي"""
    short_uuid = uuid.uuid4().hex[:8].upper()
    return f"TXN-{short_uuid}"


def extract_links(text: str) -> List[str]:
    """
    استخراج جميع الروابط بالترتيب مع الحفاظ التام على الرابط الأصلي دون أي تعديل.
    يدعم Midasbuy، يوتيوب، تيك توك، فيسبوك، تيليجرام، وروابط المنتجات.
    """
    if not text:
        return []

    found = []
    # البحث عن الروابط الصريحة
    for match in URL_PATTERN.finditer(text):
        link = match.group(0).strip()
        # تصحيح الروابط التي تبدأ بـ www. لتصبح قابلة للفتح
        if link.lower().startswith("www."):
            link = "https://" + link
        elif link.lower().startswith("t.me/"):
            link = "https://" + link

        # إزالة علامات الترقيم العرضية في نهاية الرابط إن وُجدت
        link = re.sub(r'[,;.!?)>]+$', '', link)

        if link and link not in found:
            found.append(link)

    return found


def has_links(text: str) -> bool:
    """فحص ما إذا كانت الرسالة تحتوي على أي روابط صالحة"""
    if not text:
        return False
    return bool(URL_PATTERN.search(text))


def separate_link_and_text(text: str) -> Tuple[List[str], str]:
    """
    فصل الروابط عن النص المصاحب
    يرجع (قائمة الروابط، النص الخالي من الروابط)
    """
    links = extract_links(text)
    clean_text = text
    for link in links:
        clean_text = clean_text.replace(link, "")
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return links, clean_text
