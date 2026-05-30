# Use official slim Python base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7860 \
    HOME=/home/user

# Install system dependencies (including wget for model download)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    ffmpeg \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user (required by Hugging Face Spaces)
RUN useradd -m -u 1000 user

# Set working directory
WORKDIR $HOME/app

# Copy requirements and install python packages first (layer caching)
COPY --chown=user:user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY --chown=user:user . .

# -----------------------------------------------------------------------
# Download the real MediaPipe Pose Landmarker model from Google's CDN.
# The repo only contains a Git-LFS pointer (132 bytes) which HF Spaces
# cannot resolve.  We overwrite it here with the actual 9.4 MB binary.
# -----------------------------------------------------------------------
RUN mkdir -p ai-gym-coach-main/main_app/ml_models && \
    wget -q \
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task" \
    -O ai-gym-coach-main/main_app/ml_models/pose_landmarker_full.task && \
    echo "Model downloaded: $(du -sh ai-gym-coach-main/main_app/ml_models/pose_landmarker_full.task)"

# Ensure the database can be written by the non-root user
RUN touch ai-gym-coach-main/main_app/data.db && \
    chown -R user:user ai-gym-coach-main/main_app && \
    chmod 666 ai-gym-coach-main/main_app/data.db

# Switch to non-root user
USER user

# Expose Streamlit port
EXPOSE 7860

# Run Streamlit
CMD ["streamlit", "run", "ai-gym-coach-main/main_app/main.py", \
     "--server.port=7860", \
     "--server.address=0.0.0.0", \
     "--server.enableCORS=false", \
     "--server.enableXsrfProtection=false"]
