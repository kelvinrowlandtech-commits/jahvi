import subprocess
cmd = ['ffmpeg', '-i', 'JAHVI/backend/ultraplay.mp4', '-vn', 'output.mp3']
subprocess.run(cmd, check=True)
