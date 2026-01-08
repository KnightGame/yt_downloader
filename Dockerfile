# Gunakan Python base image
FROM python:3.11-slim

# Install ffmpeg dan dependencies sistem
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements dulu untuk caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Update yt-dlp ke versi terbaru
RUN pip install --no-cache-dir --upgrade yt-dlp

# Copy semua file project
COPY . .

# Buat folder downloads
RUN mkdir -p /tmp/downloads

# Expose port (Railway akan set PORT env variable)
EXPOSE $PORT

# PENTING: Gunakan 1 worker saja untuk menghindari masalah file sharing
# Tambahkan --preload untuk shared memory
CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 300 --log-level info --access-logfile - --error-logfile -
