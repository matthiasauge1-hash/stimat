FROM python:3.11-slim

# Dépendances système pour CadQuery / OpenCASCADE
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copie et install des dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie du code
COPY app/ ./app/
COPY index.html .

# Expose le port Railway
EXPOSE 8000

# Sert aussi index.html via FastAPI (static file)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
