import os
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

# Point storage at temp dirs BEFORE cortex.config loads settings.
_tmp = Path(tempfile.mkdtemp(prefix="cortex-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'test.db'}"
os.environ["ARTIFACTS_DIR"] = str(_tmp / "artifacts")
os.environ["BROWSER_PROFILES_DIR"] = str(_tmp / "profiles")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ["VAULT_FERNET_KEY"] = Fernet.generate_key().decode()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
