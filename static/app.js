// Check dependencies on load
document.addEventListener('DOMContentLoaded', () => {
    checkDependencies();
    setupEventListeners();
});

async function checkDependencies() {
    try {
        const response = await fetch('/check-dependencies');
        const data = await response.json();
        
        const ytdlpBadge = document.getElementById('ytdlp-badge');
        const ffmpegBadge = document.getElementById('ffmpeg-badge');
        
        ytdlpBadge.textContent = `yt-dlp: ${data.ytdlp ? '✓' : '✗'}`;
        ytdlpBadge.className = `badge ${data.ytdlp ? 'success' : 'error'}`;
        
        ffmpegBadge.textContent = `ffmpeg: ${data.ffmpeg ? '✓' : '✗'}`;
        ffmpegBadge.className = `badge ${data.ffmpeg ? 'success' : 'error'}`;
    } catch (error) {
        console.error('Failed to check dependencies:', error);
    }
}

function setupEventListeners() {
    const fetchBtn = document.getElementById('fetch-btn');
    const urlInput = document.getElementById('url-input');
    
    fetchBtn.addEventListener('click', fetchVideoInfo);
    urlInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') fetchVideoInfo();
    });
    
    // Tab switching
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.format-list').forEach(l => l.classList.remove('active'));
            
            btn.classList.add('active');
            const tabId = btn.dataset.tab + '-formats';
            document.getElementById(tabId).classList.add('active');
        });
    });
}

async function fetchVideoInfo() {
    const urlInput = document.getElementById('url-input');
    const fetchBtn = document.getElementById('fetch-btn');
    const errorMessage = document.getElementById('error-message');
    const videoInfo = document.getElementById('video-info');
    
    const url = urlInput.value.trim();
    if (!url) {
        showError('Masukkan URL video terlebih dahulu');
        return;
    }
    
    // Show loading
    fetchBtn.disabled = true;
    fetchBtn.querySelector('.btn-text').style.display = 'none';
    fetchBtn.querySelector('.btn-loading').style.display = 'flex';
    errorMessage.style.display = 'none';
    videoInfo.style.display = 'none';
    
    try {
        const response = await fetch('/get-info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Gagal mengambil informasi video');
        }
        
        displayVideoInfo(data, url);
        
    } catch (error) {
        showError(error.message);
    } finally {
        fetchBtn.disabled = false;
        fetchBtn.querySelector('.btn-text').style.display = 'inline';
        fetchBtn.querySelector('.btn-loading').style.display = 'none';
    }
}

function displayVideoInfo(data, url) {
    const videoInfo = document.getElementById('video-info');
    
    document.getElementById('video-thumbnail').src = data.thumbnail || '';
    document.getElementById('video-title').textContent = data.title;
    document.getElementById('video-uploader').textContent = data.uploader;
    document.getElementById('video-platform').textContent = data.platform;
    document.getElementById('video-duration').textContent = formatDuration(data.duration);
    
    // Populate audio options
    const audioOptions = document.getElementById('audio-options');
    audioOptions.innerHTML = '';
    data.audio_formats.forEach(fmt => {
        const option = createFormatOption(fmt, 'audio', url, data.title);
        audioOptions.appendChild(option);
    });
    
    // Populate video options
    const videoOptions = document.getElementById('video-options');
    videoOptions.innerHTML = '';
    data.video_formats.forEach(fmt => {
        const option = createFormatOption(fmt, 'video', url, data.title);
        videoOptions.appendChild(option);
    });
    
    videoInfo.style.display = 'block';
}

function createFormatOption(fmt, type, url, title) {
    const div = document.createElement('div');
    div.className = 'format-option';
    
    const quality = type === 'audio' 
        ? `${fmt.abr || '?'}kbps`
        : `${fmt.height}p`;
    
    const size = fmt.filesize 
        ? formatFileSize(fmt.filesize)
        : 'Unknown size';
    
    div.innerHTML = `
        <div class="quality">${quality}</div>
        <div class="size">${size}</div>
    `;
    
    div.addEventListener('click', () => {
        document.querySelectorAll('.format-option').forEach(o => o.classList.remove('selected'));
        div.classList.add('selected');
        startDownload(url, type, fmt.id, title);
    });
    
    return div;
}

async function startDownload(url, type, formatId, title) {
    const downloadSection = document.getElementById('download-section');
    const downloadStatus = document.getElementById('download-status');
    const downloadPercent = document.getElementById('download-percent');
    const progressFill = document.getElementById('progress-fill');
    const downloadFileBtn = document.getElementById('download-file-btn');
    
    downloadSection.style.display = 'block';
    downloadFileBtn.style.display = 'none';
    downloadStatus.textContent = 'Memulai download...';
    downloadPercent.textContent = '0%';
    progressFill.style.width = '0%';
    
    try {
        const response = await fetch('/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, type, format_id: formatId, title })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Gagal memulai download');
        }
        
        // Poll for progress
        pollProgress(data.download_id);
        
    } catch (error) {
        downloadStatus.textContent = `Error: ${error.message}`;
        progressFill.style.background = 'var(--error)';
    }
}

async function pollProgress(downloadId) {
    const downloadStatus = document.getElementById('download-status');
    const downloadPercent = document.getElementById('download-percent');
    const progressFill = document.getElementById('progress-fill');
    const downloadFileBtn = document.getElementById('download-file-btn');
    
    const poll = async () => {
        try {
            const response = await fetch(`/progress/${downloadId}`);
            const data = await response.json();
            
            if (data.status === 'downloading') {
                downloadStatus.textContent = 'Mengunduh...';
                downloadPercent.textContent = `${Math.round(data.progress)}%`;
                progressFill.style.width = `${data.progress}%`;
                setTimeout(poll, 500);
            } else if (data.status === 'completed') {
                downloadStatus.textContent = 'Download selesai!';
                downloadPercent.textContent = '100%';
                progressFill.style.width = '100%';
                downloadFileBtn.style.display = 'flex';
                downloadFileBtn.onclick = () => {
                    window.location.href = `/download-file/${downloadId}`;
                };
            } else if (data.status === 'error') {
                downloadStatus.textContent = `Error: ${data.message}`;
                progressFill.style.background = 'var(--error)';
            } else {
                setTimeout(poll, 500);
            }
        } catch (error) {
            downloadStatus.textContent = 'Error: Connection lost';
        }
    };
    
    poll();
}

function formatDuration(seconds) {
    if (!seconds) return '--:--';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function formatFileSize(bytes) {
    if (!bytes) return '';
    const mb = bytes / (1024 * 1024);
    if (mb < 1) {
        return `${(bytes / 1024).toFixed(1)} KB`;
    }
    return `${mb.toFixed(1)} MB`;
}

function showError(message) {
    const errorMessage = document.getElementById('error-message');
    errorMessage.textContent = message;
    errorMessage.style.display = 'block';
}