# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY dashboard.py ./
COPY .streamlit/ ./.streamlit/
COPY entrypoint.sh ./

# Create directory for temporary files
RUN mkdir -p /tmp/downloads

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DOWNLOAD_DIR=/tmp/downloads

# Default CMD runs the Streamlit dashboard (web service).
# The cron service overrides this with: ./entrypoint.sh
CMD streamlit run dashboard.py --server.port=$PORT --server.address=0.0.0.0
