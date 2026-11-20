-- =============================================================================
-- VIP STORE – GAMING SERVICES: Supabase Cloud Database Schema
-- Run this script in the Supabase SQL Editor to set up persistent cloud tables.
-- =============================================================================

-- 1. جدول الفواتير والعمليات مع الحسابات المالية ومنع تكرار أرقام الطلبات
CREATE TABLE IF NOT EXISTS invoices (
    id BIGSERIAL PRIMARY KEY,
    order_number TEXT UNIQUE NOT NULL,
    invoice_number TEXT,
    date TEXT,
    customer_name TEXT,
    customer_phone TEXT,
    account_name TEXT,
    player_id TEXT,
    items_json JSONB,
    subtotal NUMERIC(12, 2) DEFAULT 0.00,
    tax_rate NUMERIC(6, 4) DEFAULT 0.0000,
    tax_amount NUMERIC(12, 2) DEFAULT 0.00,
    total_amount NUMERIC(12, 2) DEFAULT 0.00, -- الإيرادات (سعر البيع)
    cost NUMERIC(12, 2) DEFAULT 0.00,         -- التكلفة (سعر الشراء)
    expenses NUMERIC(12, 2) DEFAULT 0.00,     -- المصروفات
    losses NUMERIC(12, 2) DEFAULT 0.00,       -- الخسائر
    net_profit NUMERIC(12, 2) DEFAULT 0.00,   -- صافي الربح
    notes TEXT,
    status TEXT DEFAULT 'approved',
    pdf_path TEXT,
    image_path TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- فهارس للبحث السريع
CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_order_number ON invoices(UPPER(order_number));
CREATE INDEX IF NOT EXISTS idx_invoices_date ON invoices(date);

-- 2. جدول الإعدادات وحفظ معرف الرسالة المثبتة
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. جدول سجل نشر تيليجرام
CREATE TABLE IF NOT EXISTS telegram_posts (
    id BIGSERIAL PRIMARY KEY,
    order_number TEXT REFERENCES invoices(order_number) ON DELETE CASCADE,
    chat_id TEXT,
    chat_title TEXT,
    message_id BIGINT,
    posted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    status TEXT DEFAULT 'SUCCESS'
);

-- تمكين Row Level Security (RLS) اختياري لحماية البيانات
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE telegram_posts ENABLE ROW LEVEL SECURITY;

-- سياسة وصول للخدمة
CREATE POLICY "Allow service role full access" ON invoices FOR ALL USING (true);
CREATE POLICY "Allow service role full access to settings" ON settings FOR ALL USING (true);
CREATE POLICY "Allow service role full access to posts" ON telegram_posts FOR ALL USING (true);
