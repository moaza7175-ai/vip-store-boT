"""
database.py - قاعدة البيانات الدائمة لنظام VIP STORE
Persistent Database Manager supporting:
1. SQLite (ACID-compliant, zero-downtime, local file data/vip_store.db)
2. Supabase Cloud Sync (PostgreSQL cloud database if credentials provided)
3. Excel & CSV financial exports
4. Duplicate order prevention & Telegram publish audit logs
"""

import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from config import DB_PATH, SUPABASE_URL, SUPABASE_KEY, OUTPUT_DIR

logger = logging.getLogger(__name__)

# --- تهيئة عميل Supabase إذا توفرت المفاتيح ---
_supabase_client = None

def get_supabase_client():
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            from supabase import create_client
            _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
            logger.info("تم الاتصال بـ Supabase بنجاح!")
            return _supabase_client
        except Exception as e:
            logger.warning(f"تعذر الاتصال بـ Supabase: {e}")
            return None
    return None


class Database:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """إنشاء الجداول والقيود الأساسية"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # جدول الفواتير الرئيسي مع قيد الفرادة على رقم الطلب (UNIQUE order_number)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_number TEXT UNIQUE NOT NULL,
                invoice_number TEXT,
                date TEXT,
                customer_name TEXT,
                customer_phone TEXT,
                account_name TEXT,
                player_id TEXT,
                items_json TEXT,
                subtotal REAL DEFAULT 0.0,
                tax_rate REAL DEFAULT 0.0,
                tax_amount REAL DEFAULT 0.0,
                total_amount REAL DEFAULT 0.0,
                cost REAL DEFAULT 0.0,
                expenses REAL DEFAULT 0.0,
                losses REAL DEFAULT 0.0,
                net_profit REAL DEFAULT 0.0,
                notes TEXT,
                status TEXT DEFAULT 'draft',
                pdf_path TEXT,
                image_path TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """)

            # جدول سجل نشر تيليجرام (Telegram Post Audit Log)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS telegram_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_number TEXT,
                chat_id TEXT,
                chat_title TEXT,
                message_id INTEGER,
                posted_at TEXT,
                status TEXT DEFAULT 'SUCCESS',
                FOREIGN KEY(order_number) REFERENCES invoices(order_number)
            );
            """)

            # جدول الإعدادات العامة وحفظ معرف الرسالة المثبتة
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT
            );
            """)

            # فهارس للبحث السريع
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_order_number ON invoices(order_number);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON invoices(status);")
            conn.commit()
            logger.info("تم تهيئة قاعدة بيانات VIP STORE بنجاح.")

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """استرجاع قيمة إعداد"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        """حفظ أو تحديث إعداد"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;
            """, (key, str(value), now_str))
            conn.commit()

        sb = get_supabase_client()
        if sb:
            try:
                sb.table("settings").upsert({"key": key, "value": str(value), "updated_at": now_str}).execute()
            except Exception as e:
                logger.warning(f"Supabase set_setting error: {e}")

    def order_exists(self, order_number: str) -> bool:
        """التحقق مما إذا كان رقم الطلب مسجلاً مسبقاً لمنع التكرار"""
        if not order_number:
            return False
        clean_num = order_number.strip().upper()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM invoices WHERE UPPER(order_number) = ?", (clean_num,))
            return cursor.fetchone() is not None

    def get_invoice_by_order(self, order_number: str) -> Optional[Dict[str, Any]]:
        """جلب تفاصيل الفاتورة بواسطة رقم الطلب"""
        if not order_number:
            return None
        clean_num = order_number.strip().upper()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM invoices WHERE UPPER(order_number) = ?", (clean_num,))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                try:
                    d["items"] = json.loads(d.get("items_json") or "[]")
                except Exception:
                    d["items"] = []
                return d
            return None

    def save_invoice(self, data: Dict[str, Any]) -> int:
        """
        حفظ أو تحديث فاتورة في قاعدة البيانات مع الحسابات المالية،
        والمزامنة التلقائية مع Supabase إن وُجد.
        """
        order_num = str(data.get("order_number") or "").strip().upper()
        if not order_num:
            raise ValueError("رقم الطلب مطلوب ولا يمكن أن يكون فارغاً!")

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        items = data.get("items", [])
        items_json = json.dumps(items, ensure_ascii=False) if isinstance(items, list) else str(items)

        revenue = float(data.get("total_amount", 0.0) or data.get("total", 0.0))
        cost = float(data.get("cost", 0.0))
        expenses = float(data.get("expenses", 0.0))
        losses = float(data.get("losses", 0.0))
        net_profit = revenue - cost - expenses - losses

        subtotal = float(data.get("subtotal", revenue))
        tax_rate = float(data.get("tax_rate", 0.0))
        tax_amount = float(data.get("tax_amount", 0.0))

        record = {
            "order_number": order_num,
            "invoice_number": str(data.get("invoice_number", f"INV-{order_num}")),
            "date": str(data.get("date", now_str)),
            "customer_name": str(data.get("customer_name", "عميل VIP STORE")),
            "customer_phone": str(data.get("customer_phone", "")),
            "account_name": str(data.get("account_name", "")),
            "player_id": str(data.get("player_id", "")),
            "items_json": items_json,
            "subtotal": subtotal,
            "tax_rate": tax_rate,
            "tax_amount": tax_amount,
            "total_amount": revenue,
            "cost": cost,
            "expenses": expenses,
            "losses": losses,
            "net_profit": net_profit,
            "notes": str(data.get("notes", "")),
            "status": str(data.get("status", "draft")),
            "pdf_path": str(data.get("pdf_path", "")),
            "image_path": str(data.get("image_path", "")),
            "created_at": str(data.get("created_at", now_str)),
            "updated_at": now_str,
        }

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO invoices (
                order_number, invoice_number, date, customer_name, customer_phone,
                account_name, player_id, items_json, subtotal, tax_rate, tax_amount,
                total_amount, cost, expenses, losses, net_profit, notes, status,
                pdf_path, image_path, created_at, updated_at
            ) VALUES (
                :order_number, :invoice_number, :date, :customer_name, :customer_phone,
                :account_name, :player_id, :items_json, :subtotal, :tax_rate, :tax_amount,
                :total_amount, :cost, :expenses, :losses, :net_profit, :notes, :status,
                :pdf_path, :image_path, :created_at, :updated_at
            )
            ON CONFLICT(order_number) DO UPDATE SET
                customer_name = excluded.customer_name,
                customer_phone = excluded.customer_phone,
                account_name = excluded.account_name,
                player_id = excluded.player_id,
                items_json = excluded.items_json,
                subtotal = excluded.subtotal,
                tax_rate = excluded.tax_rate,
                tax_amount = excluded.tax_amount,
                total_amount = excluded.total_amount,
                cost = excluded.cost,
                expenses = excluded.expenses,
                losses = excluded.losses,
                net_profit = excluded.net_profit,
                notes = excluded.notes,
                status = excluded.status,
                pdf_path = CASE WHEN excluded.pdf_path != '' THEN excluded.pdf_path ELSE invoices.pdf_path END,
                image_path = CASE WHEN excluded.image_path != '' THEN excluded.image_path ELSE invoices.image_path END,
                updated_at = excluded.updated_at;
            """, record)
            conn.commit()
            last_id = cursor.lastrowid

        # مزامنة سحابية مع Supabase إن وُجد العميل
        sb = get_supabase_client()
        if sb:
            try:
                sb_data = dict(record)
                sb.table("invoices").upsert(sb_data, on_conflict="order_number").execute()
                logger.info(f"تمت مزامنة الفاتورة #{order_num} مع Supabase.")
            except Exception as e:
                logger.warning(f"خطأ أثناء المزامنة مع Supabase للفاتورة #{order_num}: {e}")

        return last_id

    def update_financials(self, order_number: str, cost: float, expenses: float = 0.0, losses: float = 0.0) -> Dict[str, Any]:
        """تحديث بيانات التكاليف والمصروفات وحساب صافي الربح"""
        inv = self.get_invoice_by_order(order_number)
        if not inv:
            raise ValueError(f"الطلب #{order_number} غير موجود في قاعدة البيانات!")

        revenue = float(inv.get("total_amount", 0.0))
        net_profit = revenue - cost - expenses - losses
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE invoices SET
                cost = ?,
                expenses = ?,
                losses = ?,
                net_profit = ?,
                updated_at = ?
            WHERE UPPER(order_number) = ?;
            """, (cost, expenses, losses, net_profit, now_str, order_number.strip().upper()))
            conn.commit()

        # مزامنة سحابية
        sb = get_supabase_client()
        if sb:
            try:
                sb.table("invoices").update({
                    "cost": cost,
                    "expenses": expenses,
                    "losses": losses,
                    "net_profit": net_profit,
                    "updated_at": now_str
                }).eq("order_number", order_number.strip().upper()).execute()
            except Exception as e:
                logger.warning(f"Supabase update error: {e}")

        return {
            "order_number": order_number,
            "revenue": revenue,
            "cost": cost,
            "expenses": expenses,
            "losses": losses,
            "net_profit": net_profit
        }

    def update_status(self, order_number: str, status: str, pdf_path: str = None, image_path: str = None):
        """تحديث حالة الفاتورة (draft, approved, published)"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if pdf_path and image_path:
                cursor.execute("""
                UPDATE invoices SET status = ?, pdf_path = ?, image_path = ?, updated_at = ?
                WHERE UPPER(order_number) = ?;
                """, (status, pdf_path, image_path, now_str, order_number.strip().upper()))
            elif pdf_path:
                cursor.execute("""
                UPDATE invoices SET status = ?, pdf_path = ?, updated_at = ?
                WHERE UPPER(order_number) = ?;
                """, (status, pdf_path, now_str, order_number.strip().upper()))
            else:
                cursor.execute("""
                UPDATE invoices SET status = ?, updated_at = ?
                WHERE UPPER(order_number) = ?;
                """, (status, now_str, order_number.strip().upper()))
            conn.commit()

        sb = get_supabase_client()
        if sb:
            try:
                payload = {"status": status, "updated_at": now_str}
                if pdf_path:
                    payload["pdf_path"] = pdf_path
                if image_path:
                    payload["image_path"] = image_path
                sb.table("invoices").update(payload).eq("order_number", order_number.strip().upper()).execute()
            except Exception as e:
                logger.warning(f"Supabase status update error: {e}")

    def record_telegram_post(self, order_number: str, chat_id: str, chat_title: str, message_id: int, status: str = "SUCCESS"):
        """تسجيل عملية نشر الفاتورة في جروب تيليجرام"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        clean_num = order_number.strip().upper()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO telegram_posts (order_number, chat_id, chat_title, message_id, posted_at, status)
            VALUES (?, ?, ?, ?, ?, ?);
            """, (clean_num, str(chat_id), str(chat_title), message_id, now_str, status))
            # تحديث حالة الفاتورة أيضاً إلى published
            cursor.execute("""
            UPDATE invoices SET status = 'published', updated_at = ? WHERE UPPER(order_number) = ?;
            """, (now_str, clean_num))
            conn.commit()

        sb = get_supabase_client()
        if sb:
            try:
                sb.table("telegram_posts").insert({
                    "order_number": clean_num,
                    "chat_id": str(chat_id),
                    "chat_title": str(chat_title),
                    "message_id": message_id,
                    "posted_at": now_str,
                    "status": status
                }).execute()
                sb.table("invoices").update({"status": "published", "updated_at": now_str}).eq("order_number", clean_num).execute()
            except Exception as e:
                logger.warning(f"Supabase post log error: {e}")

    def get_cumulative_metrics(self) -> Dict[str, Any]:
        """حساب الإجماليات والأرباح التراكمية"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT 
                COUNT(*) as total_orders,
                COALESCE(SUM(total_amount), 0.0) as total_revenue,
                COALESCE(SUM(cost), 0.0) as total_cost,
                COALESCE(SUM(expenses), 0.0) as total_expenses,
                COALESCE(SUM(losses), 0.0) as total_losses,
                COALESCE(SUM(net_profit), 0.0) as total_net_profit,
                COALESCE(MAX(updated_at), '') as last_updated
            FROM invoices;
            """)
            row = cursor.fetchone()
            d = dict(row)
            d["total_invoices"] = d["total_orders"]
            rev = d["total_revenue"]
            profit = d["total_net_profit"]
            d["profit_margin"] = (profit / rev * 100.0) if rev > 0 else 0.0
            d["avg_profit_per_order"] = (profit / d["total_orders"]) if d["total_orders"] > 0 else 0.0
            if not d.get("last_updated"):
                d["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return d

    def get_all_invoices(self, limit: int = 500) -> List[Dict[str, Any]]:
        """جلب جميع الفواتير مرتبة من الأحدث"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM invoices ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            result = []
            for r in rows:
                item = dict(r)
                try:
                    item["items"] = json.loads(item.get("items_json") or "[]")
                except Exception:
                    item["items"] = []
                result.append(item)
            return result

    def export_to_excel(self, output_path: Optional[Path] = None) -> Path:
        """تصدير سجل الفواتير والحسابات إلى ملف Excel احترافي يدعم العربية"""
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        if output_path is None:
            now_slug = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = OUTPUT_DIR / f"VIP_STORE_Invoices_{now_slug}.xlsx"

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "سجل فواتير VIP STORE"
        ws.sheet_view.rightToLeft = True

        # تنسيق العنوان الرئيسي
        ws.merge_cells("A1:N1")
        title_cell = ws["A1"]
        title_cell.value = "VIP STORE – GAMING SERVICES | سجل الفواتير والحسابات التراكمية"
        title_cell.font = Font(name="Arial", size=14, bold=True, color="FFFFFF")
        title_cell.fill = PatternFill(start_color="092A53", end_color="092A53", fill_type="solid")
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 35

        # ترويسة الأعمدة
        headers = [
            "م", "رقم الطلب", "التاريخ", "العميل", "الهاتف",
            "اسم الحساب", "ID الحساب", "المنتجات / الباقة",
            "الإيرادات (البيع)", "التكلفة (الشراء)", "المصروفات", "الخسائر",
            "صافي الربح", "الحالة"
        ]

        header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="103A6E", end_color="103A6E", fill_type="solid")
        header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
        thin_border = Border(
            left=Side(style='thin', color='DDDDDD'),
            right=Side(style='thin', color='DDDDDD'),
            top=Side(style='thin', color='DDDDDD'),
            bottom=Side(style='thin', color='DDDDDD')
        )

        ws.row_dimensions[2].height = 28
        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(row=2, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            cell.border = thin_border

        invoices = self.get_all_invoices(limit=1000)
        row_idx = 3

        for i, inv in enumerate(invoices, 1):
            ws.row_dimensions[row_idx].height = 22
            items_desc = ", ".join([f"{it.get('name', '')} (x{it.get('quantity', 1)})" for it in inv.get("items", [])])
            if not items_desc:
                items_desc = "شحن ألعاب"

            status_map = {
                "draft": "مسودة",
                "approved": "معتمد",
                "published": "تم النشر في الجروب"
            }
            status_disp = status_map.get(inv.get("status"), inv.get("status"))

            row_data = [
                i,
                f"#{inv.get('order_number')}",
                inv.get("date"),
                inv.get("customer_name"),
                inv.get("customer_phone") or "—",
                inv.get("account_name") or "—",
                inv.get("player_id") or "—",
                items_desc,
                float(inv.get("total_amount", 0.0)),
                float(inv.get("cost", 0.0)),
                float(inv.get("expenses", 0.0)),
                float(inv.get("losses", 0.0)),
                float(inv.get("net_profit", 0.0)),
                status_disp
            ]

            is_even = (i % 2 == 0)
            row_fill = PatternFill(start_color="F9FAFC" if is_even else "FFFFFF", fill_type="solid")

            for col_idx, val in enumerate(row_data, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.font = Font(name="Arial", size=10)
                cell.fill = row_fill
                cell.border = thin_border
                
                # تنسيق الأرقام والعملات
                if col_idx in [9, 10, 11, 12, 13]:
                    cell.number_format = '#,##0.00'
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                    if col_idx == 13:
                        # تلوين صافي الربح
                        cell.font = Font(name="Arial", size=10, bold=True, color="008000" if val >= 0 else "CC0000")
                else:
                    cell.alignment = Alignment(horizontal="center", vertical="center")

            row_idx += 1

        # صف الإجماليات في النهاية
        metrics = self.get_cumulative_metrics()
        ws.row_dimensions[row_idx].height = 26
        ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=8)
        tot_label = ws.cell(row=row_idx, column=1, value="الإجماليات التراكمية (VIP STORE TOTALS):")
        tot_label.font = Font(name="Arial", size=11, bold=True, color="092A53")
        tot_label.alignment = Alignment(horizontal="center", vertical="center")

        ws.cell(row=row_idx, column=9, value=metrics["total_revenue"]).number_format = '#,##0.00'
        ws.cell(row=row_idx, column=10, value=metrics["total_cost"]).number_format = '#,##0.00'
        ws.cell(row=row_idx, column=11, value=metrics["total_expenses"]).number_format = '#,##0.00'
        ws.cell(row=row_idx, column=12, value=metrics["total_losses"]).number_format = '#,##0.00'
        ws.cell(row=row_idx, column=13, value=metrics["total_net_profit"]).number_format = '#,##0.00'

        for c in range(1, 15):
            cell = ws.cell(row=row_idx, column=c)
            cell.font = Font(name="Arial", size=11, bold=True)
            cell.fill = PatternFill(start_color="E9F0F8", fill_type="solid")
            cell.border = thin_border

        # ضبط عرض الأعمدة تلقائياً
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

        wb.save(str(output_path))
        logger.info(f"تم تصدير ملف الإكسل إلى: {output_path}")
        return output_path

    def export_to_csv(self, output_path: Optional[Path] = None) -> Path:
        """تصدير سجل الفواتير إلى ملف CSV (UTF-8 مع BOM لدعم إكسل العربي)"""
        import csv

        if output_path is None:
            now_slug = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = OUTPUT_DIR / f"VIP_STORE_Invoices_{now_slug}.csv"

        invoices = self.get_all_invoices(limit=1000)
        headers = [
            "رقم الطلب", "التاريخ", "العميل", "الهاتف",
            "اسم الحساب", "ID الحساب", "المنتجات",
            "الإيرادات", "التكلفة", "المصروفات", "الخسائر",
            "صافي الربح", "الحالة"
        ]

        with open(str(output_path), mode="w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for inv in invoices:
                items_desc = ", ".join([f"{it.get('name', '')} (x{it.get('quantity', 1)})" for it in inv.get("items", [])])
                writer.writerow([
                    f"#{inv.get('order_number')}",
                    inv.get("date"),
                    inv.get("customer_name"),
                    inv.get("customer_phone") or "",
                    inv.get("account_name") or "",
                    inv.get("player_id") or "",
                    items_desc,
                    f"{inv.get('total_amount', 0.0):.2f}",
                    f"{inv.get('cost', 0.0):.2f}",
                    f"{inv.get('expenses', 0.0):.2f}",
                    f"{inv.get('losses', 0.0):.2f}",
                    f"{inv.get('net_profit', 0.0):.2f}",
                    inv.get("status")
                ])

        return output_path

    def get_backup_db_path(self) -> Path:
        """الحصول على مسار ملف قاعدة بيانات SQLite لعمل نسخة احتياطية"""
        return self.db_path


# كائن قاعدة البيانات المفرد
db = Database()
