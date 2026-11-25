// Shared by all pages: the "Download video" button for a finished video.
// The backend is a different server, so we fetch the real file (with the login cookie), then save it.
import { API_BASE_URL } from './url.js';

window.JahviDownload = (() => {
  async function fetchWithRefresh(url) {
    let response = await fetch(url, { credentials: 'include' });
    if (response.status === 401) {
      const refresh = await fetch(`${API_BASE_URL}/auth/refresh`, { method: 'POST', credentials: 'include' });
      if (!refresh.ok) {
        window.JahviAuth?.clearSession();
        window.location.replace('login.html');
        throw new Error('Please sign in again.');
      }
      response = await fetch(url, { credentials: 'include' });
    }
    return response;
  }

  function saveBlob(blob, filename) {
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
  }

  // videoPath: '/api/videos/<id>/video' (as sent by the backend) or a full URL.
  async function fromServer(videoPath, filename, button) {
    const label = button?.textContent;
    if (button) { button.disabled = true; button.textContent = 'Downloading…'; }
    try {
      const url = /^https?:/.test(videoPath) ? videoPath : `${API_BASE_URL}${videoPath}`;
      const response = await fetchWithRefresh(url);
      if (response.status === 410 || response.status === 404) {
        throw new Error('This video expired and was removed. Videos are kept for 5 hours.');
      }
      if (!response.ok) throw new Error(`Download failed (${response.status}).`);
      saveBlob(await response.blob(), filename);
    } catch (error) {
      window.alert(error.message || 'Download failed. Please try again.');
    } finally {
      if (button) { button.disabled = false; button.textContent = label; }
    }
  }

  function fromBlobUrl(blobUrl, filename) {
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  // "expires in 4h 20m" from an ISO time (or '' when unknown)
  function expiryText(iso) {
    const ms = new Date(iso).getTime() - Date.now();
    if (!iso || !Number.isFinite(ms)) return 'Videos are kept for 5 hours — download yours.';
    if (ms <= 0) return 'This video is about to be removed — download it now.';
    const minutes = Math.floor(ms / 60000);
    const left = minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes}m`;
    return `Kept for another ${left} — download it before then.`;
  }

  return { fromServer, fromBlobUrl, expiryText };
})();
