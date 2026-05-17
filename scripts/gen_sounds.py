"""Generate cat sound WAV files. Run once during setup."""
import sys
sys.path.insert(0, ".")
from action.voice import ensure_sounds
ensure_sounds()
print("Sound files generated successfully.")
