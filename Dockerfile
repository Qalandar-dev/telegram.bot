FROM python:3.11-slim

# ffmpeg audio/video konvertatsiya uchun, fonts-dejavu esa matn qo'shish (tahrirlash) uchun kerak
RUN apt-get update && apt-get install -y ffmpeg fonts-dejavu-core && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# yt-dlp'ni har deployda majburan eng so'nggi (pre-release) versiyaga yangilaymiz
# (YouTube tez-tez o'z tizimini o'zgartirib turadi, eski versiya ishlamay qolishi mumkin)
RUN pip install --no-cache-dir --upgrade --pre yt-dlp

COPY . .

CMD ["python", "video_downloader_bot.py"]
