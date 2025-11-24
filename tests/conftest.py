import sys
from pathlib import Path

# Ensure the repo root is on sys.path so imports like `import server` resolve
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
