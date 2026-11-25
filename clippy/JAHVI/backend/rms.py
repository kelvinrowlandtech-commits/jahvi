import librosa
import numpy as np
from scipy.signal import butter, sosfilt


def detect_beats(audio_path):
    """Return strong, chronologically ordered beat timestamps."""

    audio_samples, sample_rate = librosa.load(audio_path, sr=None)
    _harmonic, percussive = librosa.effects.hpss(audio_samples)

    hop_length = 512

    _tempo, beat_frames = librosa.beat.beat_track(
        y=percussive,
        sr=sample_rate,
        hop_length=hop_length
    )

    if len(beat_frames) == 0:
        return []

    def normalize(values):
        value_min, value_max = values.min(), values.max()
        return (values - value_min) / (value_max - value_min + 1e-9)

    def bandpass_rms(audio, sr, low, high):
        sos = butter(
            4, [low, high],
            btype="bandpass",
            fs=sr,
            output="sos"
        )
        filtered = sosfilt(sos, audio)
        return librosa.feature.rms(
            y=filtered,
            hop_length=hop_length
        )[0]

    rms = librosa.feature.rms(
        y=percussive,
        hop_length=hop_length
    )[0]

    bass_energy = bandpass_rms(
        audio_samples, sample_rate, 40, 150
    )

    onset_strength = librosa.onset.onset_strength(
        y=percussive,
        sr=sample_rate,
        hop_length=hop_length
    )

    shortest_length = min(
        len(rms),
        len(bass_energy),
        len(onset_strength)
    )

    if shortest_length == 0:
        return []

    combined_score = (
        0.45 * normalize(bass_energy[:shortest_length])
        + 0.30 * normalize(rms[:shortest_length])
        + 0.25 * normalize(onset_strength[:shortest_length])
    )

    valid_frames = np.asarray(
        [f for f in beat_frames if 0 <= f < shortest_length],
        dtype=int
    )

    if len(valid_frames) == 0:
        return []

    beat_scores = combined_score[valid_frames]

    threshold = (
        np.percentile(beat_scores, 75)
        if len(beat_scores) > 1
        else beat_scores[0]
    )

    candidate_frames = valid_frames[beat_scores >= threshold]

    candidate_times = librosa.frames_to_time(
        candidate_frames,
        sr=sample_rate,
        hop_length=hop_length
    )

    selected_times = []

    for beat_time in sorted(candidate_times):
        beat_time = float(beat_time)

        if not selected_times or beat_time - selected_times[-1] >= 0.5:
            selected_times.append(beat_time)

    return [
        round(t, 3)
        for t in selected_times
        if np.isfinite(t) and t >= 0
    ]