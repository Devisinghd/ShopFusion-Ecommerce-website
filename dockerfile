# Use official Python runtime as base image
FROM python:3.11-slim

# Set environment variables
# Prevents Python from writing pyc files
ENV PYTHONDONTWRITEBYTECODE=1
# Prevents Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy project
COPY . /app/

# Create necessary directories
RUN mkdir -p /app/staticfiles /app/media

# Collect static files for production
RUN DJANGO_SECRET_KEY=build-only-not-for-runtime ALLOW_SQLITE=True ALLOWED_HOSTS=localhost EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend python manage.py collectstatic --noinput

# Expose port
EXPOSE 8000

# Run the application
CMD ["gunicorn", "mysite.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
