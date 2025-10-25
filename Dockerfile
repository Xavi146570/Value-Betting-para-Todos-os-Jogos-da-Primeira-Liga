# Usa Python 3.11 estável com bibliotecas de sistema necessárias
FROM python:3.11-slim-buster

# Define diretório de trabalho
WORKDIR /app

# Instala dependências de sistema necessárias para compilação (se necessário)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copia requirements.txt primeiro (para cache Docker eficiente)
COPY requirements.txt .

# Atualiza pip e instala dependências Python
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copia resto do código
COPY . .

# Cria diretório para dados persistentes
RUN mkdir -p /app/data

# Expõe a porta
EXPOSE $PORT

# Comando de inicialização
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port $PORT"]
