
FROM python:3.11-slim
 
# ffmpeg audio konvertatsiya uchun kerak
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
 
WORKDIR /app
 
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# yt-dlp'ni har deployda majburan eng so'nggi versiyaga yangilaymiz
# (YouTube tez-tez o'z tizimini o'zgartirib turadi, eski versiya ishlamay qolishi mumkin)
RUN pip install --no-cache-dir --upgrade yt-dlp
 
COPY . .
 
CMD ["python", "video_downloader_bot.py"]
 
