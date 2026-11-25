from rms import detect_beats

audio_path = "JAHVI/backend/.mp3"

beats = detect_beats(audio_path)

print(beats)