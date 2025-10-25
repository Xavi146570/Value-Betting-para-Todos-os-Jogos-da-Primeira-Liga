# Usa Python 3.11 com Debian Bookworm
FROM python:3.11-slim-bookworm

# Define diretório de trabalho
WORKDIR /app

# Define variáveis de ambiente
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Instala dependências de sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libc6-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copia e instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copia código da aplicação
COPY . .
RUN mkdir -p /app/data

# Expõe porta
EXPOSE 8000

# MUDANÇA PRINCIPAL: Executar app.py diretamente (Python controla a porta)
CMD ["python", "app.py"]
