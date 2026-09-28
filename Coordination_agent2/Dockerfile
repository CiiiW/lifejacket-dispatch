FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

COPY requirements-lifejacket-ui.txt .
RUN pip install -r requirements-lifejacket-ui.txt

COPY lifejacket_app.py lifejacket_vertex.py agent2_prompt_library.json ./
COPY agent1_incident_database.csv agent2_rescue_center_directory.csv ./

EXPOSE 8080

CMD ["sh", "-c", "streamlit run lifejacket_app.py --server.port=${PORT:-8080} --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false"]
