FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PORT=7860

WORKDIR /app

# تثبيت الحزم والخطوط العربية الأساسية
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu \
    fonts-freefont-ttf \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# تثبيت مكتبات بايثون
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ ملفات البوت
COPY . .

EXPOSE 7860

# تشغيل البوت عبر المراقب الذاتي لضمان العمل 24/7
CMD ["python", "watchdog.py"]
