// Shared by Dashboard, Beat Sync Lab and Headshot Lab: poll one job until it finishes.
// Progress lives in the database, so closing the tab never loses the work.
import { API_BASE_URL } from './url.js';

window.JahviJobs = (() => {
  const POLL_MS = 5000;
  const QUEUED_POLL_MS = 8000; // waiting in line: poll less often to spare the server
  const base = () => API_BASE_URL;

  async function fetchJob(jobId) {
    const url = `${base()}/api/videos/${encodeURIComponent(jobId)}`;
    try {
      let response = await fetch(url, { credentials: 'include' });
      if (response.status === 401) {
        // The access token expired: renew it from the refresh cookie, or send them to log in.
        const refresh = await fetch(`${base()}/auth/refresh`, { method: 'POST', credentials: 'include' });
        if (!refresh.ok) {
          window.JahviAuth?.clearSession();
          window.location.replace('login.html');
          return null;
        }
        response = await fetch(url, { credentials: 'include' });
      }
      if (response.status === 404) return { missing: true };
      return response.ok ? await response.json() : null;
    } catch {
      return null; // network blip — keep trying
    }
  }

  // Resolves with the finished job (it has video_url); throws with a readable message otherwise.
  async function waitForJob(jobId, onUpdate = () => {}) {
    while (true) {
      const job = await fetchJob(jobId);
      if (job === null) {
        onUpdate({ status: 'reconnecting' });
      } else if (job.missing) {
        throw new Error('This video could not be found. It may have expired.');
      } else {
        if (job.status === 'failed') {
          await window.JahviAuth?.loadUserAndCredits().catch(() => null);
          throw new Error(job.error || 'Processing failed. Please try again.');
        }
        if (job.status === 'expired') throw new Error('This video expired and was removed.');
        if (job.status === 'completed' && job.video_url) {
          await window.JahviAuth?.loadUserAndCredits().catch(() => null);
          return job;
        }
        onUpdate(job);
      }
      const waiting = job && job.status === 'queued';
      await new Promise(resolve => setTimeout(resolve, waiting ? QUEUED_POLL_MS : POLL_MS));
    }
  }

  return { waitForJob };
})();
