import { API_BASE_URL } from './url.js';
const jobsList = document.getElementById('jobsList');
const jobsStatus = document.getElementById('jobsStatus');
const refreshJobsButton = document.getElementById('refreshJobsBtn');
const jobsWaveform = document.getElementById('jobsWaveform');
const jobsTotal = document.getElementById('jobsTotal');
const jobsActive = document.getElementById('jobsActive');
const jobsReady = document.getElementById('jobsReady');
let refreshInProgress = false;
let hasActiveJobs = false;

const waveformLevels = [0.22, 0.38, 0.56, 0.31, 0.76, 0.47, 0.9, 0.54, 0.34, 0.66, 0.43, 0.82, 0.27, 0.59, 0.96, 0.48, 0.7, 0.36, 0.63, 0.29, 0.88, 0.51, 0.74, 0.4, 0.58, 0.92, 0.33, 0.68, 0.46, 0.8, 0.25, 0.61];

function fillWaveform(container) {
  container.replaceChildren(...waveformLevels.map((level, index) => {
    const bar = document.createElement('span');
    bar.style.height = `${18 + level * 76}%`;
    bar.style.setProperty('--bar-delay', `${(index % 11) * -0.09}s`);
    return bar;
  }));
}

fillWaveform(jobsWaveform);

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString();
}

function addDetail(container, label, value) {
  const row = document.createElement('div');
  row.className = 'job-detail';
  const name = document.createElement('span');
  name.textContent = label;
  const detail = document.createElement('strong');
  detail.textContent = value || '—';
  row.append(name, detail);
  container.appendChild(row);
}

function timeLeft(iso) {
  const ms = new Date(iso).getTime() - Date.now();
  if (!Number.isFinite(ms) || ms <= 0) return 'any moment now';
  const minutes = Math.floor(ms / 60000);
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes}m`;
}

function renderJob(job) {
  const card = document.createElement('article');
  card.className = `job-card job-card-${job.status}`;
  const heading = document.createElement('div');
  heading.className = 'job-card-heading';
  const title = document.createElement('h2');
  title.textContent = job.edit_type === 'beatsync' ? 'Beat Sync' : job.edit_type === 'extraction' ? 'Headshot Extraction' : 'Dashboard Montage';
  const state = document.createElement('span');
  state.className = `job-state job-state-${job.status}`;
  state.textContent = job.status;
  heading.append(title, state);
  card.appendChild(heading);

  const details = document.createElement('div');
  details.className = 'job-details';
  addDetail(details, 'Job ID', job.id);
  if (job.status === 'queued') addDetail(details, 'Queue position', String((job.queue_position ?? 0) + 1));
  addDetail(details, 'Created', formatDate(job.created_at));
  addDetail(details, 'Started', formatDate(job.started_at));
  if (job.completed_at) addDetail(details, 'Finished', formatDate(job.completed_at));
  if (job.expires_at) addDetail(details, 'Expires in', `${timeLeft(job.expires_at)} — download it before then`);
  card.appendChild(details);

  if (job.status === 'processing' || job.status === 'queued') {
    const progress = document.createElement('div');
    progress.className = 'job-progress';
    const waveform = document.createElement('div');
    waveform.className = `job-waveform${job.status === 'processing' ? ' is-active' : ''}`;
    waveform.setAttribute('aria-hidden', 'true');
    fillWaveform(waveform);
    const bar = document.createElement('progress');
    bar.max = 100;
    bar.value = Number(job.progress_percent) || 0;
    const message = document.createElement('p');
    message.textContent = job.progress_message || (job.status === 'queued' ? 'Waiting in the queue' : 'Processing video');
    const percent = document.createElement('span');
    percent.className = 'job-progress-percent';
    percent.textContent = job.status === 'queued' ? 'QUEUED' : `${Math.round(Number(job.progress_percent) || 0)}%`;
    progress.append(waveform, bar, message, percent);
    card.appendChild(progress);
  }

  if (job.status === 'expired') {
    const expired = document.createElement('p');
    expired.className = 'job-error';
    expired.textContent = 'This video expired and was removed from storage.';
    card.appendChild(expired);
  }

  if (job.error) {
    const error = document.createElement('p');
    error.className = 'job-error';
    error.textContent = job.error;
    card.appendChild(error);
  }

  if (job.video_url) {
    const video = document.createElement('video');
    video.controls = true;
    video.preload = 'metadata';
    video.crossOrigin = 'use-credentials';
    video.src = new URL(job.video_url, API_BASE_URL || window.location.href).href;
    video.className = 'job-video';
    card.appendChild(video);

    const download = document.createElement('button');
    download.type = 'button';
    download.className = 'job-download';
    download.textContent = 'Download video';
    download.addEventListener('click', () => window.JahviDownload.fromServer(`${job.video_url}?download=true`, `jahvi-${job.edit_type}.mp4`, download));
    card.appendChild(download);
  }

  if (job.status === 'completed' || job.status === 'failed' || job.status === 'expired') {
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'job-delete';
    remove.textContent = 'Delete job';
    remove.addEventListener('click', () => deleteJob(job.id, remove));
    card.appendChild(remove);
  }
  return card;
}

async function getJobs() {
  let response = await fetch(`${API_BASE_URL}/api/videos`, { credentials: 'include' });
  if (response.status === 401) {
    const refresh = await fetch(`${API_BASE_URL}/auth/refresh`, { method: 'POST', credentials: 'include' });
    if (refresh.ok) response = await fetch(`${API_BASE_URL}/api/videos`, { credentials: 'include' });
  }
  if (response.status === 401) {
    window.JahviAuth?.clearSession();
    window.location.replace('login.html');
    return null;
  }
  if (!response.ok) throw new Error(`Could not load jobs (${response.status}).`);
  return response.json();
}

async function loadJobs() {
  if (refreshInProgress) return;
  refreshInProgress = true;
  refreshJobsButton.disabled = true;
  try {
    const result = await getJobs();
    if (!result) return;
    const videos = result.videos || [];
    hasActiveJobs = videos.some(job => job.status === 'queued' || job.status === 'processing');
    const activeCount = videos.filter(job => job.status === 'queued' || job.status === 'processing').length;
    const readyCount = videos.filter(job => job.status === 'completed').length;
    jobsTotal.textContent = String(videos.length).padStart(2, '0');
    jobsActive.textContent = String(activeCount).padStart(2, '0');
    jobsReady.textContent = String(readyCount).padStart(2, '0');
    jobsWaveform.classList.toggle('is-active', activeCount > 0);
    if (videos.length) {
      jobsList.replaceChildren(...videos.map(renderJob));
      jobsStatus.textContent = `${videos.length} ${videos.length === 1 ? 'job' : 'jobs'} in your library`;
    } else {
      const empty = document.createElement('div');
      empty.className = 'jobs-empty';
      const title = document.createElement('h2');
      title.textContent = 'No edits in the queue yet';
      const message = document.createElement('p');
      message.textContent = 'Your next render will show up here with its progress and playback.';
      const link = document.createElement('a');
      link.href = 'dashboard.html';
      link.textContent = 'Start an edit';
      empty.append(title, message, link);
      jobsList.replaceChildren(empty);
      jobsStatus.textContent = 'Your video library is ready';
    }
  } catch (error) {
    jobsStatus.textContent = error.message || 'Could not load jobs.';
  } finally {
    refreshInProgress = false;
    refreshJobsButton.disabled = false;
  }
}

async function deleteJob(jobId, button) {
  button.disabled = true;
  try {
    const response = await fetch(`${API_BASE_URL}/api/videos/${encodeURIComponent(jobId)}`, {
      method: 'DELETE',
      credentials: 'include',
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.detail || `Could not delete job (${response.status}).`);
    }
    await loadJobs();
  } catch (error) {
    jobsStatus.textContent = error.message || 'Could not delete job.';
    button.disabled = false;
  }
}

refreshJobsButton.addEventListener('click', loadJobs);
window.JahviAuth.initialize().then(user => {
  if (!user) {
    window.location.replace('login.html');
    return;
  }
  loadJobs();
  window.setInterval(() => {
    const isPlaying = [...jobsList.querySelectorAll('video')].some(video => !video.paused && !video.ended);
    if (hasActiveJobs && !isPlaying) loadJobs();
  }, 7000);
});
