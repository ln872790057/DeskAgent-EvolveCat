"""PyInstaller build script for macOS."""
import subprocess
import sys

def build():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=deskagent",
        "--windowed",
        "--onefile",
        "--add-data", "ui/resources:ui/resources",
        "--add-data", "config.example.json:.",
        "main.py",
    ]
    subprocess.run(cmd, check=True)
    print("Build complete: dist/deskagent")
    print("Note: macOS users need to grant Accessibility permission.")
    print("First run: right-click app → Open → confirm.")


if __name__ == "__main__":
    build()
