# Použij Python 3.11 slim
FROM python:3.11.8-slim

# Nastav pracovní adresář
WORKDIR /app

# Zkopíruj všechny soubory
COPY . .

# Aktualizuj pip a nainstaluj závislosti
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Expose port (Render používá proměnnou PORT)
ENV PORT=10000

# Spuštění gunicorn s environment portem
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000", "--workers", "1"]