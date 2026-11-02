import os

# Force the offline provider before app.config is imported anywhere.
os.environ["PROVIDER"] = "mock"
os.environ["OPENAI_API_KEY"] = ""

from app.config import get_settings

get_settings.cache_clear()
