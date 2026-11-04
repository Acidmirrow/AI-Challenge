import os

os.environ["PROVIDER"] = "mock"
os.environ["OPENAI_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""

from app.config import get_settings

get_settings.cache_clear()
