// ============================================================
// Jahvi Headshot Extraction Lab — plain JS, no framework.
// The extraction lab uploads one prepared video and shows the returned result.
// ============================================================

import { API_BASE_URL } from './url.js';
import { prepareForPage } from './video_prep.js';

const pageState = {
  videoFile: null,      // the one video the user picked, or null if none yet
  maxGapSeconds: 5,      // default max gap, matches the "5s" chip being pre-selected
  exportRatio: '9:16',   // default export ratio
  patch: false,          // patchless mode is the default
};

// ---------- Side nav open/close (mobile drawer) ----------
const hamburgerMenuButton = document.getElementById('menuBtn');
const sidebarPanel = document.getElementById('sidePanel');
const sidebarOverlay = document.getElementById('navOverlay');

hamburgerMenuButton.addEventListener('click', () => {
  sidebarPanel.classList.add('open');
  sidebarOverlay.classList.add('open');
});
sidebarOverlay.addEventListener('click', () => {
  sidebarPanel.classList.remove('open');
  sidebarOverlay.classList.remove('open');
});

// ---------- Video upload, preview, replace, delete ----------
const clipBoxElement = document.querySelector('.clip-box');
const clipLabelElement = document.querySelector('.clip-label');
const clipCountLabel = document.getElementById('clipCount');
const clipInputElement = document.getElementById('videoInput');

const reelElement = document.getElementById('reel');
const videoPreviewCard = document.getElementById('videoPreviewCard');
const videoPreviewPlayer = document.getElementById('videoPreviewPlayer');
const replaceVideoBtn = document.getElementById('replaceVideoBtn');
const deleteVideoBtn = document.getElementById('deleteVideoBtn');
let localVideoPreviewUrl = null;

function setLocalVideoPreview(file) {
  if (localVideoPreviewUrl) URL.revokeObjectURL(localVideoPreviewUrl);
  localVideoPreviewUrl = URL.createObjectURL(file);
  videoPreviewPlayer.src = localVideoPreviewUrl;
}

function clearLocalVideoPreview() {
  if (localVideoPreviewUrl) URL.revokeObjectURL(localVideoPreviewUrl);
  localVideoPreviewUrl = null;
}

clipBoxElement.addEventListener('click', () => clipInputElement.click());
replaceVideoBtn.addEventListener('click', () => clipInputElement.click());

clipInputElement.addEventListener('change', () => {
  const selectedFile = clipInputElement.files[0];
  if (!selectedFile) return;

  pageState.videoFile = selectedFile;
  window.JahviTimeline?.clear();

  setLocalVideoPreview(selectedFile);
  videoPreviewPlayer.load();

  reelElement.style.display = 'none';
  videoPreviewCard.style.display = 'block';

  clipCountLabel.textContent = '1 / 1';

  updateGenerateButtonState();
});

deleteVideoBtn.addEventListener('click', () => {
  pageState.videoFile = null;

  clipInputElement.value = '';
  videoPreviewPlayer.pause();
  clearLocalVideoPreview();
  videoPreviewPlayer.removeAttribute('src');
  videoPreviewPlayer.load();

  videoPreviewCard.style.display = 'none';
  reelElement.style.display = 'flex';

  clipBoxElement.classList.remove('filled');
  clipBoxElement.textContent = '1';
  clipLabelElement.textContent = 'Empty';
  clipCountLabel.textContent = '0 / 1';
  window.JahviTimeline?.clear();

  updateGenerateButtonState();
});

// ---------- Max gap picker (chips + custom input) ----------
const gapButtons = document.querySelectorAll('.gap-btn');
const customGapInput = document.getElementById('customGapInput');

gapButtons.forEach(button => {
  button.addEventListener('click', () => {
    pageState.maxGapSeconds = Number(button.dataset.gap);

    gapButtons.forEach(b => b.classList.remove('active'));
    button.classList.add('active');

    // A chip was picked, so clear any custom value the user typed
    customGapInput.value = '';
  });
});

// 5s is selected by default
document.querySelector('[data-gap="5"]').classList.add('active');

customGapInput.addEventListener('input', () => {
  const typedValue = Number(customGapInput.value);
  if (typedValue > 0) {
    pageState.maxGapSeconds = typedValue;
    gapButtons.forEach(b => b.classList.remove('active')); // custom value overrides the chips
  }
});

// ---------- Export ratio picker ----------
const ratioButtons = document.querySelectorAll('.ratio-btn');

ratioButtons.forEach(ratioButtonElement => {
  ratioButtonElement.addEventListener('click', () => selectExportRatio(ratioButtonElement.dataset.ratio));
});

function selectExportRatio(ratioValue){
  pageState.exportRatio = ratioValue;
  ratioButtons.forEach(ratioButtonElement => {
    ratioButtonElement.classList.toggle('active', ratioButtonElement.dataset.ratio === ratioValue);
  });
}

selectExportRatio('9:16');

document.querySelectorAll('.mode-btn').forEach(button => {
  button.addEventListener('click', () => {
    pageState.patch = button.dataset.patch === 'true';
    document.querySelectorAll('.mode-btn').forEach(item => item.classList.toggle('active', item === button));
  });
});

// ---------- Generate CTA (kept in sync across mobile bar + desktop sidebar) ----------
const generateButtons = [document.getElementById('generateBtn'), document.getElementById('generateBtnDesktop')];
const ctaStatusLabels = [document.getElementById('ctaStatus'), document.getElementById('ctaStatusDesktop')];

function updateGenerateButtonState(){
  const hasVideo = !!pageState.videoFile;
  const hasTimestamps = window.JahviTimeline?.hasTimestamps() === true;

  generateButtons.forEach(buttonElement => buttonElement.disabled = !(hasVideo && hasTimestamps));
  ctaStatusLabels.forEach(labelElement => {
    if (!hasVideo) labelElement.textContent = 'Add a video to continue';
    else if (!hasTimestamps) labelElement.textContent = 'Add at least one timeline bar';
    else labelElement.textContent = 'Ready to extract';
  });
}

// ============================================================
// Extract headshots — the main flow, fires only on button click.
// Submit a job, poll its extraction status, then load the returned video bytes.
// ============================================================
const previewIdleElement = document.getElementById('previewIdle');
const previewProcessingElement = document.getElementById('previewProcessing');
const previewVideoElement = document.getElementById('previewVideo');
const previewErrorElement = document.getElementById('previewError');
const circleFillElement = document.getElementById('circleFill');
const circleLabelElement = document.getElementById('circleLabel');
const processingSubElement = document.getElementById('processingSub');
const resultStatElement = document.getElementById('resultStat');
let resultVideoUrl = null;

window.addEventListener('jahvi:timelinechange', updateGenerateButtonState);

let headshotsFoundCount = null;

// Lets video_prep.js show its steps in this page's own progress circle.
const prepUi = {
  progress: updateCircularProgress,
  sub: message => { processingSubElement.textContent = message; },
  status: message => ctaStatusLabels.forEach(label => { label.textContent = message; }),
};

generateButtons.forEach(buttonElement => buttonElement.addEventListener('click', startExtraction));

async function startExtraction(){
  generateButtons.forEach(buttonElement => { buttonElement.disabled = true; buttonElement.textContent = 'Extracting…'; });
  ctaStatusLabels.forEach(labelElement => labelElement.textContent = 'Getting ready…');
  resultStatElement.style.display = 'none';
  headshotsFoundCount = null;

  try {
    // Credits first, so we don't spend minutes shrinking a video we can't process.
    const creditMessage = await window.JahviAuth.validateProcessingFiles([]);
    if (creditMessage) throw new Error(creditMessage);
    showProcessingState();

    // Shrink + trim the video and rebuild the headshot stamps to match it.
    const upload = await prepareForPage(pageState.videoFile, window.JahviTimeline.getTimestamps(), prepUi);
    const sizeMessage = await window.JahviAuth.validateProcessingFiles([upload.file]);
    if (sizeMessage) throw new Error(sizeMessage);
    headshotsFoundCount = upload.stamps.length;
    showProcessingState({ stage: 'Uploading extraction job', percentage: 0 });
    ctaStatusLabels.forEach(labelElement => { labelElement.textContent = 'Uploading extraction job…'; });

    const formData = new FormData();
    formData.append('video', upload.file, upload.file.name);
    formData.append('headshot_timestamps', JSON.stringify(upload.stamps));
    formData.append('max_gap', String(pageState.maxGapSeconds));
    formData.append('ratio', pageState.exportRatio);
    formData.append('patch', String(pageState.patch));

    const response = await fetch(`${API_BASE_URL}/extract`, {
      method: 'POST',
      body: formData,
      credentials: 'include',
    });

    if (!response.ok) {
      const responseText = await response.text();
      let errorData = {};
      try {
        errorData = responseText ? JSON.parse(responseText) : {};
      } catch {
        errorData = { detail: responseText };
      }
      if (response.status === 401) {
        window.JahviAuth?.clearSession();
        window.location.replace('login.html');
        return;
      }
      throw new Error(errorData.detail || `Extraction failed (${response.status}).`);
    }

    const submitted = await response.json();
    if (!submitted.job_id) throw new Error('The extraction server did not return a job ID.');
    await pollExtraction(submitted.job_id);

  } catch (err) {
    console.error('Extraction failed:', err);
    const message = err instanceof TypeError && err.message === 'Failed to fetch'
      ? `Could not reach the extraction server at ${API_BASE_URL}/extract. Check that the backend is running.`
      : (err.message || 'Something went wrong. Please try again.');
    showGenerateError(message);
  }
}

async function pollExtraction(jobId){
  while (true) {
    await new Promise(resolve => setTimeout(resolve, 3000));
    const response = await fetch(
      `${API_BASE_URL}/extraction_progress/${encodeURIComponent(jobId)}`,
      { credentials: 'include' },
    );
    if (!response.ok) {
      if (response.status === 401) {
        window.JahviAuth?.clearSession();
        window.location.replace('login.html');
        return;
      }
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Could not read extraction progress (${response.status}).`);
    }

    const contentType = response.headers.get('content-type') || '';
    if (contentType.startsWith('video/')) {
      const videoBlob = await response.blob();
      await showFinishedVideo(videoBlob);
      return;
    }

    const progress = await response.json();
    if (progress.status === 'failed') {
      throw new Error(progress.error || 'Extraction failed.');
    }
    showProcessingState({ stage: progress.stage, percentage: progress.percentage });
    ctaStatusLabels.forEach(labelElement => {
      labelElement.textContent = `${progress.stage || 'Processing'}${Number.isFinite(progress.percentage) ? ` · ${progress.percentage}%` : ''}`;
    });
  }
}

function updateCircularProgress(progressPercent){
  const clampedPercent = Math.max(0, Math.min(100, progressPercent));
  circleFillElement.style.setProperty('--progress-percent', clampedPercent);
  circleLabelElement.textContent = `${Math.round(clampedPercent)}%`;
}

function showProcessingState({ indeterminate = false, stage = 'Preparing video', percentage = 0 } = {}){
  const actions = document.getElementById('resultActions');
  if (actions) actions.style.display = 'none';
  previewIdleElement.style.display = 'none';
  previewVideoElement.style.display = 'none';
  previewProcessingElement.style.display = 'flex';
  previewProcessingElement.classList.toggle('indeterminate', indeterminate);
  previewErrorElement.style.display = 'none';
  processingSubElement.textContent = `${stage} • Max gap ${pageState.maxGapSeconds}s`;
  updateCircularProgress(percentage);
}

async function showFinishedVideo(videoBlob){
  if (resultVideoUrl) URL.revokeObjectURL(resultVideoUrl);
  resultVideoUrl = URL.createObjectURL(videoBlob);
  previewProcessingElement.style.display = 'none';
  previewProcessingElement.classList.remove('indeterminate');
  previewIdleElement.style.display = 'none';
  previewVideoElement.style.display = 'block';
  previewVideoElement.src = resultVideoUrl;

  // Show the selected headshot count and final duration once video metadata loads.
  previewVideoElement.addEventListener('loadedmetadata', () => {
    const durationSeconds = Math.round(previewVideoElement.duration);
    const headshotText = headshotsFoundCount !== null ? `${headshotsFoundCount} headshots found` : 'Headshots found';
    resultStatElement.textContent = `${headshotText} • ${durationSeconds}s final video`;
    resultStatElement.style.display = 'block';
  }, { once: true });
  previewVideoElement.load();
  showResultActions();

  generateButtons.forEach(buttonElement => { buttonElement.disabled = false; buttonElement.textContent = 'Extract headshots'; });
  ctaStatusLabels.forEach(labelElement => labelElement.textContent = 'Done — extract again anytime');

  window.JahviAuth.loadUserAndCredits().catch(() => null);
}

function showGenerateError(message){
  previewProcessingElement.style.display = 'none';
  previewProcessingElement.classList.remove('indeterminate');
  previewVideoElement.style.display = 'none';
  previewIdleElement.style.display = 'flex';
  previewErrorElement.style.display = 'block';
  previewErrorElement.textContent = message;

  generateButtons.forEach(buttonElement => { buttonElement.disabled = false; buttonElement.textContent = 'Extract headshots'; });
  updateGenerateButtonState();
}

// ---------- Init ----------
window.JahviAuth.initialize().then(user => {
  if (!user) {
    window.location.replace('login.html');
  }
});
updateGenerateButtonState();

// ---- finished video: download button (the video is already in the browser as a blob) ----
function showResultActions(){
  const actions = document.getElementById('resultActions');
  const button = document.getElementById('downloadBtn');
  if (!actions || !button || !resultVideoUrl) return;
  actions.style.display = 'block';
  button.onclick = () => window.JahviDownload.fromBlobUrl(resultVideoUrl, 'jahvi-extraction.mp4');
}
