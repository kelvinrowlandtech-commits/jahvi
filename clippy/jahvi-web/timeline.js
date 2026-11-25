import { API_BASE_URL } from './url.js';
import { formatBytes, prepareForDetection } from './video_prep.js';

(() => {
  const state = { timestamps: [], stepSizes: [], duration: 0, activeIndex: -1, dragging: false };
  const track = document.getElementById('timelineTrack');
  const emptyLabel = document.getElementById('timelineEmpty');
  const addButton = document.getElementById('addBarBtn');
  const currentTimeLabel = document.getElementById('timelineCurrentTime');
  const video = document.getElementById('videoPreviewPlayer');
  const list = document.getElementById('timestampList');

  if (!track || !video) return;

  let pendingVideoSeek = null;
  const emitChange = () => window.dispatchEvent(new CustomEvent('jahvi:timelinechange'));
  const clampTime = value => Math.max(0, Math.min(state.duration || 0, value));
  const formatTime = value => {
    const minutes = Math.floor(value / 60);
    const seconds = value - minutes * 60;
    return `${String(minutes).padStart(2, '0')}:${seconds.toFixed(2).padStart(5, '0')}`;
  };

  function applyPendingVideoSeek() {
    if (pendingVideoSeek === null || video.seeking) return;
    const target = pendingVideoSeek;
    pendingVideoSeek = null;
    if (Math.abs(video.currentTime - target) > 0.001) video.currentTime = target;
  }

  function requestVideoSeek(timestamp) {
    pendingVideoSeek = clampTime(timestamp);
    applyPendingVideoSeek();
  }

  function getNeighborBoundaries(index) {
    return {
      previous: state.timestamps[index - 1],
      next: state.timestamps[index + 1],
    };
  }

  function setTimestampAtIndex(index, nextValue, { seek = true, rerender = true } = {}) {
    const parsedValue = Number(nextValue);
    if (!Number.isFinite(parsedValue)) return false;

    const candidate = clampTime(parsedValue);
    const { previous, next } = getNeighborBoundaries(index);

    if ((previous !== undefined && candidate <= previous)
      || (next !== undefined && candidate >= next)) {
      window.alert('This timestamp cannot pass the neighboring bar.');
      return false;
    }

    state.timestamps[index] = candidate;
    state.activeIndex = index;
    if (rerender) render();
    if (seek) seekTo(candidate);
    emitChange();
    return true;
  }

  function selectMarker(index) {
    state.activeIndex = index;
    track.querySelectorAll('.timeline-bar').forEach((bar, barIndex) => {
      bar.classList.toggle('active', barIndex === index);
    });
    list?.querySelectorAll('.timestamp-item').forEach((item, itemIndex) => {
      item.classList.toggle('active', itemIndex === index);
    });
  }

  function updateMarkerDisplay(index) {
    const timestamp = state.timestamps[index];
    const bar = track.querySelectorAll('.timeline-bar')[index];
    const item = list?.children[index];
    if (bar) {
      bar.style.left = `${state.duration ? (timestamp / state.duration) * 100 : 0}%`;
      bar.title = `${timestamp.toFixed(2)}s | scroll to adjust`;
      bar.setAttribute('aria-label', `Headshot at ${timestamp.toFixed(2)} seconds`);
    }
    if (item) {
      item.querySelector('.timestamp-jump').textContent = formatTime(timestamp);
      item.querySelector('.timestamp-input').value = timestamp.toFixed(2);
      item.querySelector('.timestamp-delete').setAttribute('aria-label', `Delete headshot at ${formatTime(timestamp)}`);
    }
    selectMarker(index);
  }

  function render() {
    track.querySelectorAll('.timeline-bar').forEach(bar => bar.remove());
    if (emptyLabel) emptyLabel.style.display = state.timestamps.length ? 'none' : 'block';

    state.timestamps.forEach((timestamp, index) => {
      const bar = document.createElement('button');
      bar.type = 'button';
      bar.className = `timeline-bar${index === state.activeIndex ? ' active' : ''}`;
      bar.style.left = `${state.duration ? (timestamp / state.duration) * 100 : 0}%`;
      bar.title = `${timestamp.toFixed(2)}s | scroll to adjust`;
      bar.setAttribute('aria-label', `Headshot at ${timestamp.toFixed(2)} seconds. Use the mouse wheel to adjust.`);
      bar.addEventListener('pointerdown', event => beginDrag(event, index));
      bar.addEventListener('click', () => selectMarker(index));
      bar.addEventListener('wheel', event => {
        event.preventDefault();
        const step = Number(list?.children[index]?.querySelector('.timestamp-step-select')?.value || state.stepSizes[index] || 0.4);
        adjustTimestamp(index, (event.deltaY < 0 ? -1 : 1) * step);
      }, { passive: false });
      bar.addEventListener('keydown', event => {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
        event.preventDefault();
        const step = Number(list?.children[index]?.querySelector('.timestamp-step-select')?.value || state.stepSizes[index] || 0.4);
        adjustTimestamp(index, (event.key === 'ArrowLeft' ? -1 : 1) * step);
      });
      track.appendChild(bar);
    });

    if (list) {
      list.replaceChildren();
      state.timestamps.forEach((timestamp, index) => {
        const item = document.createElement('li');
        item.className = `timestamp-item${index === state.activeIndex ? ' active' : ''}`;
        item.innerHTML = `<span class="timestamp-label">Bar ${index + 1}</span><button type="button" class="timestamp-step timestamp-step-back" aria-label="Move headshot backward">-</button><button type="button" class="timestamp-jump">${formatTime(timestamp)}</button><label class="timestamp-field"><span>Time (s)</span><input type="number" class="timestamp-input" min="0" step="0.01" value="${timestamp.toFixed(2)}" aria-label="Headshot time in seconds" /></label><select class="timestamp-step-select" aria-label="Timestamp adjustment"><option value="0.5">0.5s</option><option value="0.3">0.3s</option><option value="0.2">0.2s</option><option value="0.1">0.1s</option><option value="0.4">0.4s</option><option value="0.01">0.01s</option><option value="0.02">0.02s</option></select><button type="button" class="timestamp-step timestamp-step-forward" aria-label="Move headshot forward">+</button><button type="button" class="timestamp-delete" aria-label="Delete headshot at ${formatTime(timestamp)}">×</button>`;
        const stepSelect = item.querySelector('.timestamp-step-select');
        const timestampInput = item.querySelector('.timestamp-input');
        stepSelect.value = state.stepSizes[index] || '0.4';
        stepSelect.addEventListener('change', () => { state.stepSizes[index] = stepSelect.value; });
        item.querySelector('.timestamp-jump').addEventListener('click', () => seekTo(timestamp));
        timestampInput.addEventListener('change', event => {
          const nextValue = Number(event.target.value);
          if (!Number.isFinite(nextValue)) {
            event.target.value = timestamp.toFixed(2);
            return;
          }
          setTimestampAtIndex(index, nextValue, { seek: false, rerender: true });
        });
        item.querySelector('.timestamp-step-back').addEventListener('click', event => {
          event.stopPropagation();
          adjustTimestamp(index, -Number(item.querySelector('.timestamp-step-select').value), { seek: true });
        });
        item.querySelector('.timestamp-step-forward').addEventListener('click', event => {
          event.stopPropagation();
          adjustTimestamp(index, Number(item.querySelector('.timestamp-step-select').value), { seek: true });
        });
        item.querySelector('.timestamp-delete').addEventListener('click', () => {
          state.timestamps.splice(index, 1);
          state.stepSizes.splice(index, 1);
          state.activeIndex = -1;
          render();
          emitChange();
        });
        list.appendChild(item);
      });
    }
  }

  function seekTo(timestamp) {
    video.pause();
    requestVideoSeek(timestamp);
    if (pendingVideoSeek === null && !video.seeking) updateActive(video.currentTime);
  }

  function adjustTimestamp(index, delta, { seek = false } = {}) {
    if (setTimestampAtIndex(index, state.timestamps[index] + delta, { seek, rerender: false })) {
      updateMarkerDisplay(index);
    }
  }

  function beginDrag(event, index) {
    event.preventDefault();
    const bar = event.currentTarget;
    const pointerId = event.pointerId;
    let changed = false;
    state.dragging = true;
    selectMarker(index);
    bar.setPointerCapture(pointerId);

    const updateAtClientX = clientX => {
      const rect = track.getBoundingClientRect();
      if (!rect.width) return;
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      const candidate = Number((ratio * state.duration).toFixed(3));
      const { previous, next } = getNeighborBoundaries(index);
      if ((previous !== undefined && candidate <= previous)
        || (next !== undefined && candidate >= next)
        || Math.abs(candidate - state.timestamps[index]) < 0.001) return false;

      video.pause();
      state.timestamps[index] = candidate;
      updateMarkerDisplay(index);
      requestVideoSeek(candidate);
      changed = true;
      return true;
    };

    const move = moveEvent => updateAtClientX(moveEvent.clientX);

    const end = endEvent => {
      if (endEvent.type === 'pointerup') updateAtClientX(endEvent.clientX);
      bar.removeEventListener('pointermove', move);
      bar.removeEventListener('pointerup', end);
      bar.removeEventListener('pointercancel', end);
      if (bar.hasPointerCapture(pointerId)) bar.releasePointerCapture(pointerId);
      state.dragging = false;
      if (changed) {
        render();
        applyPendingVideoSeek();
        emitChange();
      }
    };

    bar.addEventListener('pointermove', move);
    bar.addEventListener('pointerup', end);
    bar.addEventListener('pointercancel', end);
  }

  function updateActive(currentTime) {
    currentTimeLabel.textContent = `${currentTime.toFixed(2)}s`;
    if (state.dragging) return;
    let nextIndex = -1;
    let nearestDistance = 0.2;
    state.timestamps.forEach((timestamp, index) => {
      const distance = Math.abs(timestamp - currentTime);
      if (distance <= nearestDistance) {
        nearestDistance = distance;
        nextIndex = index;
      }
    });
    if (nextIndex !== state.activeIndex) {
      state.activeIndex = nextIndex;
      render();
    }
  }

  addButton?.addEventListener('click', () => {
    if (!state.duration) return;
    const timestamp = Number(video.currentTime.toFixed(2));
    if (state.timestamps.some(existing => Math.abs(existing - timestamp) < 0.05)) return;
    const insertIndex = state.timestamps.findIndex(existing => existing > timestamp);
    const targetIndex = insertIndex === -1 ? state.timestamps.length : insertIndex;
    state.timestamps.splice(targetIndex, 0, timestamp);
    state.stepSizes.splice(targetIndex, 0, '0.4');
    state.activeIndex = targetIndex;
    render();
    emitChange();
  });

  video.addEventListener('loadedmetadata', () => {
    state.duration = Number.isFinite(video.duration) ? video.duration : 0;
    addButton.disabled = !state.duration;
    updateDetectionButton();
    render();
  });
  video.addEventListener('timeupdate', () => updateActive(video.currentTime));
  video.addEventListener('seeking', () => updateActive(video.currentTime));
  video.addEventListener('seeked', () => {
    applyPendingVideoSeek();
    if (pendingVideoSeek === null && !video.seeking) updateActive(video.currentTime);
  });

  window.JahviTimeline = {
    hasTimestamps: () => state.timestamps.length > 0,
    getTimestamps: () => [...state.timestamps],
    getDuration: () => state.duration,
    setTimestamps: timestamps => {
      if (!Array.isArray(timestamps)) return false;
      state.timestamps = [...new Set(
        timestamps
          .map(Number)
          .filter(Number.isFinite)
          .map(clampTime)
          .map(timestamp => Number(timestamp.toFixed(3)))
      )].sort((left, right) => left - right);
      state.stepSizes = state.timestamps.map(() => '0.4');
      state.activeIndex = -1;
      render();
      emitChange();
      return true;
    },
    clear: () => { state.timestamps = []; state.stepSizes = []; state.activeIndex = -1; render(); emitChange(); },
  };

  const detectButton = document.getElementById('detectHeadshotsBtn');
  const detectionStatus = document.getElementById('headshotDetectionStatus');
  const videoInput = document.getElementById('videoInput');
  const updateDetectionButton = () => {
    if (detectButton) detectButton.disabled = !videoInput?.files?.length || !state.duration;
  };

  if (detectButton && detectionStatus && videoInput) {
    videoInput.addEventListener('change', () => {
      state.duration = 0;
      updateDetectionButton();
    });
    document.getElementById('deleteVideoBtn')?.addEventListener('click', () => window.setTimeout(updateDetectionButton, 0));
    document.getElementById('replaceVideoBtn')?.addEventListener('click', () => window.setTimeout(updateDetectionButton, 0));

    detectButton.addEventListener('click', async () => {
      const videoFile = videoInput.files?.[0];
      if (!videoFile) {
        detectionStatus.textContent = 'Choose a video first.';
        updateDetectionButton();
        return;
      }

      detectButton.disabled = true;
      detectButton.textContent = 'Detecting…';
      detectionStatus.textContent = 'Preparing a lighter upload for detection…';

      try {
        const user = await window.JahviAuth?.loadUserAndCredits();
        if (!user) throw new Error('Please sign in before detecting headshots.');

        let estimatedCompressedSize = videoFile.size;
        const prep = await prepareForDetection(videoFile, percent => {
          detectionStatus.textContent = `Compressing video for upload… ${percent}% (${formatBytes(Math.min(estimatedCompressedSize, videoFile.size))} estimated)`;
        });
        estimatedCompressedSize = prep.prepared ? prep.compressedSize : videoFile.size;

        const sendFile = prep.file ?? videoFile;
        if (prep.prepared) {
          detectionStatus.textContent = `Sending compressed upload: ${formatBytes(prep.originalSize)} → ${formatBytes(prep.compressedSize)}.`;
        } else if (prep.reason === 'unsupported' || prep.reason === 'failed') {
          detectionStatus.textContent = 'Browser prep was unavailable, so the original file is being sent.';
        }

        const formData = new FormData();
        formData.append('video', sendFile, sendFile.name);
        let response = await fetch(`${API_BASE_URL}/api/detect-headshots`, {
          method: 'POST',
          body: formData,
          credentials: 'include',
        });

        if (response.status === 401) {
          const refresh = await fetch(`${API_BASE_URL}/auth/refresh`, {
            method: 'POST',
            credentials: 'include',
          });
          if (refresh.ok) {
            response = await fetch(`${API_BASE_URL}/api/detect-headshots`, {
              method: 'POST',
              body: formData,
              credentials: 'include',
            });
          }
        }
        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || `Detection failed (${response.status}).`);
        }

        const result = await response.json();
        if (!window.JahviTimeline.setTimestamps(result.timestamps)) {
          throw new Error('The server returned an invalid timestamp list.');
        }
        detectionStatus.textContent = result.count
          ? `Found ${result.count} headshot${result.count === 1 ? '' : 's'}. Review and adjust the timeline bars.`
          : 'No headshots detected. Add bars manually or try another video.';
      } catch (error) {
        detectionStatus.textContent = error.message || 'Could not detect headshots.';
      } finally {
        detectButton.textContent = 'Find headshots';
        updateDetectionButton();
      }
    });

    updateDetectionButton();
  }

  render();
})();
