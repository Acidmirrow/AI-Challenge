import os

os.environ["PROVIDER"] = "mock"
os.environ["OPENAI_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["CONTEXT_DB_PATH"] = "/tmp/lesson07-test-context.db"

from pathlib import Path

Path(os.environ["CONTEXT_DB_PATH"]).unlink(missing_ok=True)

from app.config import get_settings

get_settings.cache_clear()
