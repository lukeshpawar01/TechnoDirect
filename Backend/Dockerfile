FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .
RUN DJANGO_SECRET_KEY=build DEBUG=True python manage.py collectstatic --noinput || true

RUN useradd -m app && chown -R app /app
USER app

EXPOSE 8000
CMD ["gunicorn", "technodirect.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
