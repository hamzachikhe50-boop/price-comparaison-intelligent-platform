FROM python:3.11-slim

WORKDIR /app

# Dépendances système minimales
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Installer uniquement les dépendances nécessaires (pas tout le requirements.txt)
COPY requirements.app.txt .
RUN pip install --no-cache-dir -r requirements.app.txt

# Copier le code
COPY app/ ./app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
