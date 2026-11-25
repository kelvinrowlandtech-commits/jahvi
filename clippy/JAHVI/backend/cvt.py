import subprocess
from pathlib import Path

# PUT YOUR VIDEO PATH HERE
video_path = "JAHVI/backend/Ragnar2.mp4"

output_path = str(Path(video_path).with_suffix(".mp3"))

subprocess.run(
    [
        "ffmpeg",
        "-i", video_path,
        "-vn",
        "-acodec", "libmp3lame",
        "-q:a", "2",
        "-y",
        output_path
    ],
    check=True
)

print("Audio saved to:", output_path)