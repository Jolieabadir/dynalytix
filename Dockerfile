FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libxcb1 \
    libxcb-shm0 \
    libxcb-render0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install backend requirements
COPY data_collection/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir mediapipe==0.10.14

# Copy everything we need
COPY main.py ./main.py
COPY src/ ./src/
COPY fms/ ./fms/
COPY data_collection/backend/ ./backend/

WORKDIR /app/backend

RUN ln -s /app/fms /app/backend/fms

RUN mkdir -p videos data data/exports data/exports/fms_findings

CMD python -m uvicorn src.web.api:app --host 0.0.0.0 --port 8080
