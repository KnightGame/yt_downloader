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

# Copy semua file project
COPY . .

# Buat folder downloads
RUN mkdir -p /tmp/downloads

# Expose port
EXPOSE 8080

# Jalankan aplikasi dengan PORT dari Railway
CMD gunicorn app:app --bind 0.0.0.0:${PORT:-8080}