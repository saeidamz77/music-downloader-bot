FROM python:3.10-slim

# نصب ffmpeg و ابزارهای مورد نیاز
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# نصب پکیج‌های پایتون
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# کپی کردن کدهای پروژه
COPY . .

# دستور اجرای ربات
CMD ["python", "bot.py"]
