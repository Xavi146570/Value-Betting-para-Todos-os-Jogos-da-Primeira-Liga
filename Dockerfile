# Usa Python 3.11 com Debian Bookworm (Debian 12 - mais recente e estável)
FROM python:3.11-slim-bookworm

# Define diretório de trabalho
WORKDIR /app

# Define variáveis de ambiente para otimização
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Atualiza sistema e instala dependências mínimas necessárias
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libc6-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copia requirements.txt primeiro (otimização de cache Docker)
COPY requirements.txt .

# Atualiza pip e instala dependências Python
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copia resto do código da aplicação
COPY . .

# Cria diretório para dados persistentes
RUN mkdir -p /app/data

# Expõe porta (Railway define automaticamente via $PORT)
EXPOSE 8000

# Comando de inicialização com fallback para porta local
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
