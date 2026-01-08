import os
from flask import Flask, render_template, request, jsonify, send_file
import subprocess
import json
from pathlib import Path
import uuid
from threading import Thread, Lock
import time
import logging
import sys

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

app = Flask(__name__, 
            static_folder='static',
            static_url_path='/static',
            template_folder='templates')

# Konfigurasi
DOWNLOAD_FOLDER = '/tmp/downloads'
Path(DOWNLOAD_FOLDER).mkdir(exist_ok=True, parents=True)

# Store download progress with thread safety
download_progress = {}
progress_lock = Lock()

def check_dependencies():
    """Check yt-dlp dan ffmpeg"""
    ytdlp_ok = False
    ffmpeg_ok = False
    
    try:
        result = subprocess.run(['yt-dlp', '--version'], 
                              capture_output=True, 
                              timeout=5,
                              text=True)
        ytdlp_ok = result.returncode == 0
        if ytdlp_ok:
            logger.info(f"yt-dlp version: {result.stdout.strip()}")
        else:
            logger.error(f"yt-dlp check failed: {result.stderr}")
    except FileNotFoundError:
        logger.error("yt-dlp not found in PATH")
    except Exception as e:
        logger.error(f"yt-dlp check error: {e}")
    
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, 
                              timeout=5,
                              text=True)
        ffmpeg_ok = result.returncode == 0
        if ffmpeg_ok:
            version_line = result.stdout.split('\n')[0]
            logger.info(f"ffmpeg: {version_line}")
        else:
            logger.error(f"ffmpeg check failed: {result.stderr}")
    except FileNotFoundError:
        logger.error("ffmpeg not found in PATH")
    except Exception as e:
        logger.error(f"ffmpeg check error: {e}")
    
    return ytdlp_ok, ffmpeg_ok

@app.route('/')
def index():
    """Halaman utama"""
    logger.info("Serving index page")
    return render_template('index.html')

@app.route('/health')
def health():
    """Health check endpoint"""
    ytdlp, ffmpeg = check_dependencies()
    return jsonify({
        'status': 'ok',
        'ytdlp': ytdlp,
        'ffmpeg': ffmpeg
    }), 200

@app.route('/check-dependencies')
def check_deps():
    """Check dependencies"""
    logger.info("Checking dependencies...")
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
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'error': 'URL tidak boleh kosong'}), 400
        
        logger.info(f"Fetching info for URL: {url}")
        
        # Update yt-dlp sebelum fetch
        try:
            subprocess.run(['yt-dlp', '-U'], capture_output=True, timeout=10)
        except:
            pass
        
        command = [
            'yt-dlp',
            '--dump-json',
            '--no-playlist',
            '--no-warnings',
            '--skip-download',
            url
        ]
        
        logger.info(f"Running: {' '.join(command)}")
        
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=45
        )
        
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout
            logger.error(f"yt-dlp error (code {result.returncode}): {error_msg}")
            return jsonify({'error': f'Gagal mengambil informasi video: {error_msg[:200]}'}), 400
        
        if not result.stdout.strip():
            logger.error("Empty response from yt-dlp")
            return jsonify({'error': 'Respons kosong dari yt-dlp'}), 400
        
        try:
            info = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            logger.error(f"Output: {result.stdout[:500]}")
            return jsonify({'error': 'Format respons tidak valid'}), 500
        
        formats = info.get('formats', [])
        logger.info(f"Found {len(formats)} formats")
        
        # Extract audio formats
        audio_formats = []
        for fmt in formats:
            if fmt.get('vcodec') == 'none' and fmt.get('acodec') != 'none':
                abr = fmt.get('abr') or fmt.get('tbr') or 0
                audio_formats.append({
                    'id': fmt.get('format_id'),
                    'ext': fmt.get('ext', 'unknown'),
                    'abr': round(abr) if abr else 0,
                    'filesize': fmt.get('filesize') or fmt.get('filesize_approx'),
                    'note': fmt.get('format_note', '')
                })
        
        # Extract video formats
        seen = {}
        for fmt in formats:
            if fmt.get('vcodec') != 'none' and fmt.get('vcodec') != 'unknown':
                height = fmt.get('height', 0)
                if not height or height < 144:
                    continue
                    
                key = f"{height}p"
                filesize = fmt.get('filesize') or fmt.get('filesize_approx') or 0
                
                if key not in seen or filesize > (seen[key].get('filesize') or 0):
                    seen[key] = {
                        'id': fmt.get('format_id'),
                        'ext': fmt.get('ext', 'mp4'),
                        'resolution': fmt.get('resolution', f'{height}p'),
                        'fps': fmt.get('fps', 30),
                        'height': height,
                        'has_audio': fmt.get('acodec') != 'none',
                        'filesize': filesize,
                        'note': fmt.get('format_note', '')
                    }
        
        video_formats = sorted(seen.values(), key=lambda x: x['height'], reverse=True)
        audio_formats.sort(key=lambda x: x.get('abr', 0), reverse=True)
        
        # Fallback jika tidak ada format
        if not audio_formats and not video_formats:
            logger.warning("No suitable formats found, using best quality")
            return jsonify({
                'title': info.get('title', 'Unknown'),
                'uploader': info.get('uploader', 'Unknown'),
                'duration': info.get('duration', 0),
                'thumbnail': info.get('thumbnail'),
                'platform': info.get('extractor', 'Unknown'),
                'audio_formats': [{'id': 'bestaudio', 'ext': 'mp3', 'abr': 128, 'filesize': None, 'note': 'Best'}],
                'video_formats': [{'id': 'best', 'ext': 'mp4', 'height': 720, 'filesize': None, 'note': 'Best'}]
            })
        
        response = {
            'title': info.get('title', 'Unknown'),
            'uploader': info.get('uploader', 'Unknown'),
            'duration': info.get('duration', 0),
            'thumbnail': info.get('thumbnail'),
            'platform': info.get('extractor', 'Unknown'),
            'audio_formats': audio_formats[:10] if audio_formats else [{'id': 'bestaudio', 'ext': 'mp3', 'abr': 128, 'filesize': None}],
            'video_formats': video_formats[:15] if video_formats else [{'id': 'best', 'ext': 'mp4', 'height': 720, 'filesize': None}]
        }
        
        logger.info(f"Successfully fetched: {response['title']}")
        logger.info(f"Audio formats: {len(response['audio_formats'])}, Video formats: {len(response['video_formats'])}")
        return jsonify(response)
        
    except subprocess.TimeoutExpired:
        logger.error("Timeout when fetching info")
        return jsonify({'error': 'Timeout - URL terlalu lama diproses (45 detik)'}), 408
    except Exception as e:
        logger.error(f"Error in get_info: {e}", exc_info=True)
        return jsonify({'error': f'Error: {str(e)}'}), 500

@app.route('/download', methods=['POST'])
def download():
    """Download video/audio"""
    try:
        data = request.json
        url = data.get('url', '').strip()
        format_type = data.get('type')
        format_id = data.get('format_id')
        title = data.get('title', 'download')
        
        if not all([url, format_type, format_id]):
            return jsonify({'error': 'Data tidak lengkap'}), 400
        
        download_id = str(uuid.uuid4())
        
        # Sanitize filename
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_title = safe_title[:100] or 'download'
        
        logger.info(f"Starting download {download_id}: {safe_title} ({format_type}, format={format_id})")
        
        thread = Thread(
            target=download_file,
            args=(download_id, url, format_type, format_id, safe_title),
            daemon=True
        )
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
        with progress_lock:
            download_progress[download_id] = {
                'status': 'downloading',
                'progress': 0,
                'message': 'Memulai download...'
            }
        
        if format_type == 'audio':
            output_file = os.path.join(DOWNLOAD_FOLDER, f"{download_id}_{safe_title}.mp3")
            
            command = [
                'yt-dlp',
                '-f', format_id if format_id != 'bestaudio' else 'bestaudio',
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
            
            if format_id == 'best':
                format_str = 'best'
            else:
                format_str = f'{format_id}+bestaudio/best'
            
            command = [
                'yt-dlp',
                '-f', format_str,
                '--merge-output-format', 'mp4',
                '-o', output_file,
                '--no-playlist',
                '--newline',
                '--no-warnings',
                url
            ]
        
        logger.info(f"Download command: {' '.join(command)}")
        
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        for line in process.stdout:
            logger.info(f"yt-dlp [{download_id}]: {line.strip()}")
            if '[download]' in line and '%' in line:
                try:
                    parts = line.split()
                    for part in parts:
                        if '%' in part:
                            progress = float(part.replace('%', ''))
                            with progress_lock:
                                download_progress[download_id]['progress'] = min(progress, 99)
                            break
                except:
                    pass
        
        process.wait()
        
        if process.returncode == 0 and os.path.exists(output_file):
            filesize = os.path.getsize(output_file)
            with progress_lock:
                download_progress[download_id] = {
                    'status': 'completed',
                    'progress': 100,
                    'message': 'Download selesai!',
                    'file': output_file,
                    'filename': os.path.basename(output_file),
                    'filesize': filesize
                }
            logger.info(f"Download completed: {download_id} ({filesize} bytes) -> {output_file}")
        else:
            with progress_lock:
                download_progress[download_id] = {
                    'status': 'error',
                    'progress': 0,
                    'message': f'Download gagal (exit code: {process.returncode})'
                }
            logger.error(f"Download failed: {download_id} (exit code: {process.returncode})")
            
    except Exception as e:
        logger.error(f"Error in download_file: {e}", exc_info=True)
        with progress_lock:
            download_progress[download_id] = {
                'status': 'error',
                'progress': 0,
                'message': f'Error: {str(e)}'
            }

@app.route('/progress/<download_id>')
def get_progress(download_id):
    """Dapatkan progress download"""
    with progress_lock:
        progress = download_progress.get(download_id, {
            'status': 'not_found',
            'progress': 0,
            'message': 'Download tidak ditemukan'
        })
    return jsonify(progress)

@app.route('/download-file/<download_id>')
def download_file_route(download_id):
    """Download file yang sudah selesai"""
    with progress_lock:
        progress = download_progress.get(download_id)
    
    if not progress:
        logger.warning(f"Download ID not found: {download_id}")
        return jsonify({'error': 'Download tidak ditemukan'}), 404
    
    if progress['status'] != 'completed':
        logger.warning(f"Download not completed: {download_id} (status: {progress['status']})")
        return jsonify({'error': f'Download belum selesai (status: {progress["status"]})'}), 400
    
    file_path = progress.get('file')
    
    if not file_path:
        logger.error(f"File path missing for download_id: {download_id}")
        return jsonify({'error': 'Path file tidak ditemukan'}), 404
    
    # Validate file path
    file_path = os.path.abspath(file_path)
    download_folder_abs = os.path.abspath(DOWNLOAD_FOLDER)
    
    if not file_path.startswith(download_folder_abs):
        logger.error(f"Security: File path outside download folder: {file_path}")
        return jsonify({'error': 'Path tidak valid'}), 403
    
    if not os.path.exists(file_path):
        logger.error(f"File does not exist: {file_path}")
        return jsonify({'error': 'File tidak ditemukan di server'}), 404
    
    logger.info(f"Serving file: {file_path} ({os.path.getsize(file_path)} bytes)")
    
    def cleanup():
        time.sleep(60)  # Increased cleanup delay
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up file: {file_path}")
            with progress_lock:
                if download_id in download_progress:
                    del download_progress[download_id]
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
    
    Thread(target=cleanup, daemon=True).start()
    
    try:
        return send_file(
            file_path,
            as_attachment=True,
            download_name=progress['filename'],
            mimetype='application/octet-stream'
        )
    except Exception as e:
        logger.error(f"Error sending file: {e}")
        return jsonify({'error': f'Gagal mengirim file: {str(e)}'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting Universal Video Downloader on port {port}")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Download folder: {DOWNLOAD_FOLDER}")
    
    # Check dependencies on startup
    ytdlp, ffmpeg = check_dependencies()
    logger.info(f"Dependencies - yt-dlp: {ytdlp}, ffmpeg: {ffmpeg}")
    
    app.run(debug=False, host='0.0.0.0', port=port)
