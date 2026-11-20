"""
watchdog.py - مراقب التشغيل التلقائي والحماية من التوقف لبوت VIP STORE
Auto-Restart Supervisor & Watchdog:
- Keeps bot.py running 24/7 continuously.
- Automatically restarts bot.py if it crashes or internet disconnects.
- Logs runtime events and output to data/bot_runtime.log.
"""

import sys
import os
import time
import subprocess
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
PYTHON_EXE = sys.executable
BOT_SCRIPT = BASE_DIR / "bot.py"
LOG_FILE = BASE_DIR / "data" / "bot_runtime.log"

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


def log_event(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] [WATCHDOG] {message}"
    print(formatted, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass


def run_supervisor():
    log_event("=" * 60)
    log_event("بدء تشغيل مراقب VIP STORE (Auto-Restart Watchdog 24/7)...")
    log_event(f"مسار بايثون: {PYTHON_EXE}")
    log_event(f"مسار البوت: {BOT_SCRIPT}")
    log_event("=" * 60)

    restart_count = 0

    while True:
        start_time = time.time()
        log_event(f"🚀 جاري تشغيل بوت VIP STORE (المحاولة رقم #{restart_count + 1})...")

        try:
            # تشغيل البوت كعملية فرعية مع توجيه المخرجات
            process = subprocess.Popen(
                [PYTHON_EXE, str(BOT_SCRIPT)],
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1
            )

            # قراءة المخرجات وعرضها وتسجيلها لحظياً
            if process.stdout:
                for line in iter(process.stdout.readline, ""):
                    if line:
                        print(line, end="", flush=True)
                        try:
                            with open(LOG_FILE, "a", encoding="utf-8") as f:
                                f.write(line)
                        except Exception:
                            pass

            process.wait()
            return_code = process.returncode
            run_duration = time.time() - start_time

            restart_count += 1
            log_event(f"⚠️ توقفت عملية البوت! كود الخروج: {return_code} (استمر لمدة {run_duration:.1f} ثانية).")

            # إذا توقف بسرعة كبيرة (أقل من 3 ثوانٍ)، ننتظر 7 ثوانٍ لمنع استهلاك المعالج
            wait_time = 7 if run_duration < 3 else 2
            log_event(f"🔄 جاري إعادة تشغيل البوت تلقائياً خلال {wait_time} ثوانٍ...")
            time.sleep(wait_time)

        except KeyboardInterrupt:
            log_event("🛑 تم استلام أمر إيقاف يدوي (KeyboardInterrupt). إيقاف المراقب...")
            try:
                process.terminate()
            except Exception:
                pass
            break
        except Exception as e:
            log_event(f"❌ خطأ غير متوقع في المراقب: {e}")
            time.sleep(5)


if __name__ == "__main__":
    run_supervisor()
