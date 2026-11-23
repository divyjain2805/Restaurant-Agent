FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Prevent Python from writing .pyc files & enable unbuffered stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Expose port (default 8000)
EXPOSE 8000

# Start FastAPI application
CMD ["uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8000"]
