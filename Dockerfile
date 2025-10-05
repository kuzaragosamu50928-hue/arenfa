# Stage 1: Build stage with dependencies
FROM python:3.11-slim as builder

WORKDIR /app

# Install build essentials for potential C extensions, then clean up
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Create and activate a virtual environment
ENV VIRTUAL_ENV=/app/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install dependencies into the virtual environment
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Final production image
FROM python:3.11-slim

WORKDIR /app

# Copy the virtual environment from the builder stage
COPY --from=builder /app/venv /app/venv

# Copy application code
COPY src/ /app/src/
COPY main.py .
COPY admin_panel.html .

# Activate the virtual environment
ENV PATH="/app/venv/bin:$PATH"

# Expose the port the app runs on
EXPOSE 8080

# Set the command to run the application
CMD ["python", "main.py"]