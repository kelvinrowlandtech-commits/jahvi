// ============================================================
// Jahvi video prep — shared by Dashboard, Headshot Extraction Lab
// and Beat Sync Lab.
//
// Before upload we do this in the user's browser:
//   1. Re-encode the video at 5 Mbps (much smaller file).
//   2. Cut it down to the parts around each headshot:
//      10 seconds before each stamp and 1 second after it.
//      Windows that overlap are merged, so a gap shorter than that
//      stays whole.
//   3. Rebuild the headshot timestamps so they match the cut video.
//
// The backend gets the cut video + the new stamps. All gap logic
// (max gap, exact gap, patching) stays on the backend.
//
// If anything goes wrong (old browser, error, nothing to gain) we
// quietly return the ORIGINAL file and the ORIGINAL stamps instead.
// ============================================================

export const PREP = {
  videoMbps: 7,
  audioKbps: 128,
  secondsBefore: 10,
  secondsAfter: 1,
  confirmAboveBytes: 50 * 1024 * 1024, // ask the user before uploading more than this
};

// Pinned to the version we tested. To host it yourself, download that file
// into this folder and change the line below to './mediabunny.mjs'.
const MEDIABUNNY_URL = 'https://cdn.jsdelivr.net/npm/mediabunny@1.42.0/+esm';

// ---------- Small helpers ----------
export function formatBytes(bytes) {
  const mb = bytes / 1024 / 1024;
  if (mb >= 1024) return (mb / 1024).toFixed(2) + ' GB';
  return mb.toFixed(1) + ' MB';
}

function browserCanPrepare() {
  return typeof VideoEncoder !== 'undefined'
    && typeof AudioEncoder !== 'undefined'
    && typeof AudioBuffer !== 'undefined';
}

// ---------- Step 1: which parts of the video do we keep? ----------
// Returns a list like [{ start: 15, end: 26 }, { start: 68, end: 79 }].
export function makeRanges(stamps, before, after, duration) {
  const sorted = stamps.slice().sort(function (a, b) { return a - b; });

  const ranges = [];
  for (let i = 0; i < sorted.length; i++) {
    let start = sorted[i] - before;
    if (start < 0) start = 0;

    let end = sorted[i] + after;
    if (end > duration) end = duration;

    if (end <= start) continue;

    const last = ranges[ranges.length - 1];
    if (last && start <= last.end) {
      // overlaps (or touches) the previous window, so stretch that one
      if (end > last.end) last.end = end;
    } else {
      ranges.push({ start: start, end: end });
    }
  }
  return ranges;
}

// ---------- Step 2: where does each old stamp land in the cut video? ----------
// new stamp = (length of all kept ranges before it) + (old stamp - start of its range)
// Returns null if any stamp is not inside a kept range.
export function remapStamps(stamps, ranges) {
  const result = [];
  for (let i = 0; i < stamps.length; i++) {
    let offset = 0;
    let found = null;
    for (let j = 0; j < ranges.length; j++) {
      const r = ranges[j];
      if (stamps[i] >= r.start && stamps[i] <= r.end) {
        found = offset + (stamps[i] - r.start);
        break;
      }
      offset = offset + (r.end - r.start);
    }
    if (found === null) return null;
    result.push(Math.round(found * 1000) / 1000);
  }
  return result;
}

// ---------- Audio: cut one audio chunk so it sits exactly inside a range ----------
// Audio comes in small chunks that do not line up with our cut points.
// Without trimming, every cut would add a few milliseconds of drift.
export function trimAudioBuffer(buffer, bufferStart, rangeStart, rangeEnd) {
  const sampleRate = buffer.sampleRate;
  const bufferEnd = bufferStart + buffer.length / sampleRate;

  const keepStart = Math.max(bufferStart, rangeStart);
  const keepEnd = Math.min(bufferEnd, rangeEnd);
  if (keepEnd <= keepStart) return null;

  const from = Math.round((keepStart - bufferStart) * sampleRate);
  let to = Math.round((keepEnd - bufferStart) * sampleRate);
  if (to > buffer.length) to = buffer.length;

  const length = to - from;
  if (length <= 0) return null;
  if (from === 0 && to === buffer.length) return buffer;

  const trimmed = new AudioBuffer({
    length: length,
    numberOfChannels: buffer.numberOfChannels,
    sampleRate: sampleRate,
  });
  for (let channel = 0; channel < buffer.numberOfChannels; channel++) {
    trimmed.copyToChannel(buffer.getChannelData(channel).subarray(from, to), channel);
  }
  return trimmed;
}

// ---------- The cut + compress itself (uses Mediabunny / WebCodecs) ----------
// Returns { file, stamps } or null when there is nothing to gain.
async function cutAndCompress(lib, file, stamps, onProgress) {
  const {
    Input, Output, BlobSource, BufferTarget, Mp4OutputFormat,
    CanvasSink, CanvasSource, AudioBufferSink, AudioBufferSource, ALL_FORMATS,
  } = lib;

  const input = new Input({ source: new BlobSource(file), formats: ALL_FORMATS });

  const videoTrack = await input.getPrimaryVideoTrack();
  const audioTrack = await input.getPrimaryAudioTrack();
  if (!videoTrack) throw new Error('No video track found.');

  const duration = await input.computeDuration();
  if (!(duration > 0)) throw new Error('Could not read the video length.');

  const ranges = makeRanges(stamps, PREP.secondsBefore, PREP.secondsAfter, duration);
  if (ranges.length === 0) return null;

  // The new stamps come from the SAME ranges used to cut, so they always match.
  const newStamps = remapStamps(stamps, ranges);
  if (!newStamps) return null;

  let totalSeconds = 0;
  for (let i = 0; i < ranges.length; i++) {
    totalSeconds = totalSeconds + (ranges[i].end - ranges[i].start);
  }

  // If the result would not be smaller than the original, don't bother.
  const estimatedBytes = totalSeconds * (PREP.videoMbps * 1000000 + PREP.audioKbps * 1000) / 8;
  if (estimatedBytes >= file.size) return null;

  // Every kept frame is drawn onto this canvas (encoders need even sizes).
  let width = await videoTrack.getDisplayWidth();
  let height = await videoTrack.getDisplayHeight();
  if (width % 2 === 1) width = width - 1;
  if (height % 2 === 1) height = height - 1;

  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');

  const output = new Output({ format: new Mp4OutputFormat(), target: new BufferTarget() });

  // These two lines set the bitrate (must be whole numbers).
  const videoSource = new CanvasSource(canvas, {
    codec: 'avc',
    bitrate: Math.round(PREP.videoMbps * 1000000),
  });
  output.addVideoTrack(videoSource);

  let audioSource = null;
  if (audioTrack) {
    audioSource = new AudioBufferSource({
      codec: 'aac',
      bitrate: Math.round(PREP.audioKbps * 1000),
    });
    output.addAudioTrack(audioSource);
  }

  await output.start();

  let lastPercent = -1;
  function reportProgress(doneSeconds) {
    if (!onProgress) return;
    let percent = Math.floor((doneSeconds / totalSeconds) * 100);
    if (percent > 99) percent = 99; // 100 is reported once the file is finished
    if (percent !== lastPercent) {
      lastPercent = percent;
      onProgress(percent);
    }
  }

  // Video: copy only the kept ranges, giving each frame its new time.
  async function addVideo() {
    const sink = new CanvasSink(videoTrack, { poolSize: 1 });
    let outStart = 0;

    for (let i = 0; i < ranges.length; i++) {
      const r = ranges[i];
      let first = true;

      for await (const frame of sink.canvases(r.start, r.end)) {
        let t = frame.timestamp - r.start;
        if (t < 0) t = 0;

        ctx.drawImage(frame.canvas, 0, 0);
        await videoSource.add(outStart + t, frame.duration, { keyFrame: first });
        first = false;

        reportProgress(outStart + t);
      }

      outStart = outStart + (r.end - r.start);
    }

    videoSource.close();
  }

  // Audio: same ranges, one after another, each trimmed to the exact edges.
  async function addAudio() {
    if (!audioTrack) return;

    const sink = new AudioBufferSink(audioTrack);
    for (let i = 0; i < ranges.length; i++) {
      const r = ranges[i];
      for await (const item of sink.buffers(r.start, r.end)) {
        const piece = trimAudioBuffer(item.buffer, item.timestamp, r.start, r.end);
        if (piece) await audioSource.add(piece);
      }
    }

    audioSource.close();
  }

  await Promise.all([addVideo(), addAudio()]);
  await output.finalize();
  if (onProgress) onProgress(100);

  const blob = new Blob([output.target.buffer], { type: 'video/mp4' });
  const baseName = (file.name || 'video').replace(/\.[^.]+$/, '') || 'video';
  const cutFile = new File([blob], baseName + '.mp4', { type: 'video/mp4' });

  return { file: cutFile, stamps: newStamps };
}

// ---------- Main entry: never throws, always returns something uploadable ----------
// Returns { file, stamps, prepared, reason }.
//   prepared = true  -> file is the cut + compressed video, stamps are rebuilt
//   prepared = false -> file/stamps are the originals (reason says why)
export async function prepareUpload(file, stamps, onProgress) {
  const original = { file: file, stamps: stamps, prepared: false, reason: '' };

  if (!stamps || stamps.length === 0) { original.reason = 'no-stamps'; return original; }
  if (!browserCanPrepare()) { original.reason = 'unsupported'; return original; }

  try {
    const lib = await import(MEDIABUNNY_URL);
    const result = await cutAndCompress(lib, file, stamps, onProgress);

    if (!result) { original.reason = 'already-small'; return original; }
    if (result.file.size >= file.size) { original.reason = 'already-small'; return original; }

    return { file: result.file, stamps: result.stamps, prepared: true, reason: '' };
  } catch (error) {
    console.warn('Video prep failed, uploading the original instead:', error);
    original.reason = 'failed';
    return original;
  }
}

// ---------- Detect-only compression: lower bitrate, do not cut or remap ----------
export async function prepareForDetection(file, onProgress) {
  const original = {
    file,
    prepared: false,
    reason: '',
    originalSize: file.size,
    compressedSize: file.size,
  };

  if (!browserCanPrepare()) {
    original.reason = 'unsupported';
    return original;
  }

  try {
    const lib = await import(MEDIABUNNY_URL);
    const result = await compressWholeVideo(lib, file, onProgress);

    if (!result) {
      original.reason = 'already-small';
      return original;
    }
    if (result.file.size >= file.size) {
      original.reason = 'already-small';
      return original;
    }

    return {
      file: result.file,
      prepared: true,
      reason: '',
      originalSize: file.size,
      compressedSize: result.file.size,
    };
  } catch (error) {
    console.warn('Detection prep failed, uploading the original instead:', error);
    original.reason = 'failed';
    return original;
  }
}

async function compressWholeVideo(lib, file, onProgress) {
  const {
    Input, Output, BlobSource, BufferTarget, Mp4OutputFormat,
    CanvasSink, CanvasSource, AudioBufferSink, AudioBufferSource, ALL_FORMATS,
  } = lib;

  const input = new Input({ source: new BlobSource(file), formats: ALL_FORMATS });
  const videoTrack = await input.getPrimaryVideoTrack();
  const audioTrack = await input.getPrimaryAudioTrack();
  if (!videoTrack) throw new Error('No video track found.');

  const duration = await input.computeDuration();
  if (!(duration > 0)) throw new Error('Could not read the video length.');

  let width = await videoTrack.getDisplayWidth();
  let height = await videoTrack.getDisplayHeight();
  if (width % 2 === 1) width = width - 1;
  if (height % 2 === 1) height = height - 1;

  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');

  const output = new Output({ format: new Mp4OutputFormat(), target: new BufferTarget() });
  const videoSource = new CanvasSource(canvas, {
    codec: 'avc',
    bitrate: Math.round(PREP.videoMbps * 1000000),
  });
  output.addVideoTrack(videoSource);

  let audioSource = null;
  if (audioTrack) {
    audioSource = new AudioBufferSource({
      codec: 'aac',
      bitrate: Math.round(PREP.audioKbps * 1000),
    });
    output.addAudioTrack(audioSource);
  }

  await output.start();

  let lastPercent = -1;
  function reportProgress(doneSeconds) {
    if (!onProgress) return;
    let percent = Math.min(99, Math.floor((doneSeconds / duration) * 100));
    if (percent !== lastPercent) {
      lastPercent = percent;
      onProgress(percent);
    }
  }

  async function addVideo() {
    const sink = new CanvasSink(videoTrack, { poolSize: 1 });
    let first = true;

    for await (const frame of sink.canvases(0, duration)) {
      ctx.drawImage(frame.canvas, 0, 0);
      await videoSource.add(frame.timestamp, frame.duration, { keyFrame: first });
      first = false;
      reportProgress(frame.timestamp);
    }

    videoSource.close();
  }

  async function addAudio() {
    if (!audioTrack || !audioSource) return;
    const sink = new AudioBufferSink(audioTrack);
    for await (const item of sink.buffers(0, duration)) {
      await audioSource.add(item.buffer);
    }
    audioSource.close();
  }

  await Promise.all([addVideo(), addAudio()]);
  await output.finalize();
  if (onProgress) onProgress(100);

  const blob = new Blob([output.target.buffer], { type: 'video/mp4' });
  const baseName = (file.name || 'video').replace(/\.[^.]+$/, '') || 'video';
  return { file: new File([blob], baseName + '.mp4', { type: 'video/mp4' }) };
}

// ---------- Page wrapper: shows the steps and asks before big uploads ----------
// `ui` is three small functions each page gives us:
//   ui.progress(percent)  -> move the circle
//   ui.sub(text)          -> small line under the circle
//   ui.status(text)       -> status text on the button area
// Throws Error('Upload cancelled.') if the user says no to a big upload.
export async function prepareForPage(file, stamps, ui) {
  ui.progress(0);
  ui.sub('Shrinking and trimming your video. Keep this tab open.');
  ui.status('Step 1 of 3 • Preparing your video…');

  const prepared = await prepareUpload(file, stamps, function (percent) {
    ui.progress(percent);
    ui.status('Step 1 of 3 • Preparing your video… ' + percent + '%');
  });

  const finalSize = formatBytes(prepared.file.size);

  if (prepared.file.size > PREP.confirmAboveBytes) {
    let message;
    if (prepared.prepared) {
      message = 'Your video was shrunk from ' + formatBytes(file.size) + ' to ' + finalSize
        + '. Uploading it will use about ' + finalSize + ' of data. Continue?';
    } else if (prepared.reason === 'unsupported' || prepared.reason === 'failed') {
      message = 'Your browser could not shrink this video, so the original (' + finalSize
        + ') will be uploaded. Continue?';
    } else {
      message = 'This video will be uploaded as it is (' + finalSize + '). Continue?';
    }
    if (!window.confirm(message)) throw new Error('Upload cancelled.');
  }

  ui.status(prepared.prepared
    ? 'Step 2 of 3 • Uploading ' + finalSize + ' (was ' + formatBytes(file.size) + ')…'
    : 'Step 2 of 3 • Uploading ' + finalSize + '…');

  return { file: prepared.file, stamps: prepared.stamps };
}
