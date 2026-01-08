import os
from flask import Flask, render_template, request, jsonify, send_file
import subprocess
import json
from pathlib import Path
import uuid
from threading import Thread
import time
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Konfigurasi - Gunakan /tmp untuk Railway
DOWNLOAD_FOLDER = '/tmp/downloads'
Path(DOWNLOAD_FOLDER).mkdir(exist_ok=True, parents=True)

# Store download progress
download_progress = {}

def check_dependencies():
    """Check yt-dlp dan ffmpeg"""
    ytdlp_ok = False
    ffmpeg_ok = False
    
    try:
        result = subprocess.run(['yt-dlp', '--version'], capture_output=True, timeout=5)
        ytdlp_ok = result.returncode == 0
        logger.info(f"yt-dlp check: {ytdlp_ok}")
    except Exception as e:
        logger.error(f"yt-dlp check failed: {e}")
    
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
        ffmpeg_ok = result.returncode == 0
        logger.info(f"ffmpeg check: {ffmpeg_ok}")
    except Exception as e:
        logger.error(f"ffmpeg check failed: {e}")
    
    return ytdlp_ok, ffmpeg_ok

@app.route('/')
def index():
    """Halaman utama"""
    return render_template('index.html')

@app.route('/check-dependencies')
def check_deps():
    """Check dependencies"""
    ytdlp, ffmpeg = check_dependencies()
    return jsonify({
        'ytdlp': ytdlp,
        'ffmpeg': ffmpeg
    })

@app.route('/get-info', methods=['POST'])
def get_info():
    """Dapatkan info video dari URL"""
    try:
        data = request.json
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL tidak boleh kosong'}), 400
        
        logger.info(f"Fetching info for URL: {url}")
        
        command = [
            'yt-dlp',
            '--dump-json',
            '--no-playlist',
            '--no-warnings',
            url
        ]
        
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            logger.error(f"yt-dlp error: {result.stderr}")
            return jsonify({'error': 'Gagal mengambil informasi video'}), 400
        
        info = json.loads(result.stdout)
        
        formats = info.get('formats', [])
        
        # Extract audio formats
        audio_formats = []
        for fmt in formats:
            if fmt.get('vcodec') == 'none' and fmt.get('acodec') != 'none':
                audio_formats.append({
                    'id': fmt.get('format_id'),
                    'ext': fmt.get('ext'),
                    'abr': fmt.get('abr', 0),
                    'filesize': fmt.get('filesize') or fmt.get('filesize_approx'),
                    'note': fmt.get('format_note', '')
                })
        
        # Extract video formats (unique by height)
        seen = {}
        for fmt in formats:
            if fmt.get('vcodec') != 'none':
                height = fmt.get('height', 0)
                if height == 0:
                    continue
                    
                key = f"{height}p"
                
                if key not in seen or (fmt.get('filesize', 0) or 0) > (seen[key].get('filesize', 0) or 0):
                    seen[key] = {
                        'id': fmt.get('format_id'),
                        'ext': fmt.get('ext'),
                        'resolution': fmt.get('resolution', 'Unknown'),
                        'fps': fmt.get('fps', 0),
                        'height': height,
                        'has_audio': fmt.get('acodec') != 'none',
                        'filesize': fmt.get('filesize') or fmt.get('filesize_approx'),
                        'note': fmt.get('format_note', '')
                    }
        
        video_formats = sorted(seen.values(), key=lambda x: x['height'], reverse=True)
        audio_formats.sort(key=lambda x: x['abr'] or 0, reverse=True)
        
        response = {
            'title': info.get('title', 'Unknown'),
            'uploader': info.get('uploader', 'Unknown'),
            'duration': info.get('duration', 0),
            'thumbnail': info.get('thumbnail'),
            'platform': info.get('extractor', 'Unknown'),
            'audio_formats': audio_formats[:10],
            'video_formats': video_formats[:15]
        }
        
        logger.info(f"Successfully fetched info: {response['title']}")
        return jsonify(response)
        
    except subprocess.TimeoutExpired:
        logger.error("Timeout when fetching info")
        return jsonify({'error': 'Timeout saat mengambil informasi'}), 408
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return jsonify({'error': 'Format respons tidak valid'}), 500
    except Exception as e:
        logger.error(f"Error in get_info: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/download', methods=['POST'])
def download():
    """Download video/audio"""
    try:
        data = request.json
        url = data.get('url')
        format_type = data.get('type')
        format_id = data.get('format_id')
        title = data.get('title', 'download')
        
        if not all([url, format_type, format_id]):
            return jsonify({'error': 'Data tidak lengkap'}), 400
        
        download_id = str(uuid.uuid4())
        
        # Sanitize filename
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_title = safe_title[:100] or 'download'
        
        logger.info(f"Starting download {download_id}: {safe_title}")
        
        thread = Thread(
            target=download_file,
            args=(download_id, url, format_type, format_id, safe_title)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'download_id': download_id,
            'message': 'Download dimulai'
        })
        
    except Exception as e:
        logger.error(f"Error in download: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

def download_file(download_id, url, format_type, format_id, safe_title):
    """Background task untuk download"""
    try:
        download_progress[download_id] = {
            'status': 'downloading',
            'progress': 0,
            'message': 'Memulai download...'
        }
        
        if format_type == 'audio':
            output_file = os.path.join(DOWNLOAD_FOLDER, f"{download_id}_{safe_title}.mp3")
            
            command = [
                'yt-dlp',
                '-f', format_id,
                '--extract-audio',
                '--audio-format', 'mp3',
                '--audio-quality', '0',
                '-o', output_file,
                '--no-playlist',
                '--newline',
                '--no-warnings',
                url
            ]
        else:
            output_file = os.path.join(DOWNLOAD_FOLDER, f"{download_id}_{safe_title}.mp4")
            
            command = [
                'yt-dlp',
                '-f', f'{format_id}+bestaudio/best',
                '--merge-output-format', 'mp4',
                '-o', output_file,
                '--no-playlist',
                '--newline',
                '--no-warnings',
                url
            ]
        
        logger.info(f"Running command: {' '.join(command)}")
        
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        for line in process.stdout:
            if '[download]' in line and '%' in line:
                try:
                    parts = line.split()
                    for part in parts:
                        if '%' in part:
                            progress = float(part.replace('%', ''))
                            download_progress[download_id]['progress'] = progress
                            break
                except:
                    pass
        
        process.wait()
        
        if process.returncode == 0 and os.path.exists(output_file):
            filesize = os.path.getsize(output_file)
            download_progress[download_id] = {
                'status': 'completed',
                'progress': 100,
                'message': 'Download selesai!',
                'file': output_file,
                'filename': os.path.basename(output_file),
                'filesize': filesize
            }
            logger.info(f"Download completed: {download_id}")
        else:
            download_progress[download_id] = {
                'status': 'error',
                'progress': 0,
                'message': 'Download gagal'
            }
            logger.error(f"Download failed: {download_id}")
            
    except Exception as e:
        logger.error(f"Error in download_file: {e}", exc_info=True)
        download_progress[download_id] = {
            'status': 'error',
            'progress': 0,
            'message': str(e)
        }

@app.route('/progress/<download_id>')
def get_progress(download_id):
    """Dapatkan progress download"""
    progress = download_progress.get(download_id, {
        'status': 'not_found',
        'progress': 0,
        'message': 'Download tidak ditemukan'
    })
    return jsonify(progress)

@app.route('/download-file/<download_id>')
def download_file_route(download_id):
    """Download file yang sudah selesai"""
    progress = download_progress.get(download_id)
    
    if not progress or progress['status'] != 'completed':
        return 'File tidak ditemukan', 404
    
    file_path = progress['file']
    
    if not os.path.exists(file_path):
        return 'File tidak ditemukan', 404
    
    def cleanup():
        time.sleep(5)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
            if download_id in download_progress:
                del download_progress[download_id]
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
    
    Thread(target=cleanup, daemon=True).start()
    
    return send_file(
        file_path,
        as_attachment=True,
        download_name=progress['filename']
    )

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting app on port {port}")
    app.run(debug=False, host='0.0.0.0', port=port)
