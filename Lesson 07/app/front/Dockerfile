FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /srv

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY *.py ./
COPY .streamlit ./.streamlit

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /srv
USER appuser

EXPOSE 8501
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3).status==200 else 1)"

CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true"]
