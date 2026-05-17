"""PyInstaller build script for Windows."""
import subprocess
import sys

def build():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=deskagent",
        "--windowed",
        "--onefile",
        "--add-data", "ui/resources;ui/resources",
        "--add-data", "config.example.json;.",
        "main.py",
    ]
    subprocess.run(cmd, check=True)
    print("Build complete: dist/deskagent.exe")


if __name__ == "__main__":
    build()
