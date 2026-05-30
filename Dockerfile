# Use official slim Python base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7860 \
    HOME=/home/user

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user (required by Hugging Face Spaces)
RUN useradd -m -u 1000 user

# Set working directory
WORKDIR $HOME/app

# Copy requirements from root and install python packages
COPY --chown=user:user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY --chown=user:user . .

# Ensure the database can be initialized/written by the non-root user in main_app
RUN mkdir -p ai-gym-coach-main/main_app && \
    touch ai-gym-coach-main/main_app/data.db && \
    chown -R user:user ai-gym-coach-main/main_app && \
    chmod 666 ai-gym-coach-main/main_app/data.db

# Switch to non-root user
USER user

# Expose Streamlit port
EXPOSE 7860

# Run Streamlit pointing to main_app/main.py
CMD ["streamlit", "run", "ai-gym-coach-main/main_app/main.py", "--server.port=7860", "--server.address=0.0.0.0"]
