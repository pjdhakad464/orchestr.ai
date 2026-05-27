# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Install system dependencies (nginx, git, and curl for health check)
RUN apt-get update && apt-get install -y \
    nginx \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set up user with UID 1000 (standard for Hugging Face Spaces)
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

# Copy dependency files first to leverage Docker cache
COPY --chown=user:user pyproject.toml README.md ./

# Install python dependencies (including editable install)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e . && \
    pip install --no-cache-dir huggingface_hub

# Copy the rest of the application
COPY --chown=user:user . .

# Ensure directories exist and are writeable
RUN mkdir -p data/imdb_datasets data/wikipedia_cache data/imdb_lookup_app validated_runs && \
    chown -R user:user /home/user/app

# Switch to the non-root user
USER user

# Expose port 7860 (Hugging Face expects this port)
EXPOSE 7860

# Run the startup script
CMD ["bash", "deploy/start.sh"]
