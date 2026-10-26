FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
ENV LASTRADA_CACHE_DIR=/tmp/lastrada-cache
ENV OMP_NUM_THREADS=2
ENV MKL_NUM_THREADS=2

RUN apt-get update && apt-get install -y --no-install-recommends     ffmpeg git libsndfile1 ca-certificates     && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN python -m pip install --upgrade pip     && python -m pip install -r requirements.txt     && python -m pip install -e ".[stems]"

EXPOSE 8080

CMD ["sh", "-c", "streamlit run stem_fast_local_app.py --server.address=0.0.0.0 --server.port=${PORT:-8080} --server.headless=true --browser.gatherUsageStats=false"]
