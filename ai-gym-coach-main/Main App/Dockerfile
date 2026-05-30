# Use an official slim Python base image
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

# Copy requirements and install python packages
COPY --chown=user:user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY --chown=user:user . .

# Ensure the database can be initialized/written by the non-root user
# SQLite needs write permission on both the file and parent directory
RUN touch data.db && chown user:user data.db && chmod 666 data.db

# Switch to the non-root user
USER user

# Expose Streamlit port
EXPOSE 7860

# Command to run Streamlit
CMD ["streamlit", "run", "main.py", "--server.port=7860", "--server.address=0.0.0.0"]
