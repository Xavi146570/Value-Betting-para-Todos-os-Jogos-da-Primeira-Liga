#!/bin/bash
set -e

echo "🔍 Procurando Python 3.11..."

# Tentar encontrar Python 3.11
PYTHON_EXEC=""
for py_cmd in python3.11 python3.11m /usr/bin/python3.11 /opt/python/3.11/bin/python3.11; do
    if command -v $py_cmd &> /dev/null; then
        PYTHON_EXEC=$py_cmd
        echo "✅ Encontrado: $PYTHON_EXEC"
        break
    fi
done

if [ -z "$PYTHON_EXEC" ]; then
    echo "❌ Python 3.11 não encontrado. Usando python3 (provavelmente falhará)"
    PYTHON_EXEC="python3"
fi

# Verificar versão
$PYTHON_EXEC --version

echo "🧹 Limpando ambiente anterior..."
rm -rf .venv __pycache__

echo "🏗️ Criando ambiente virtual..."
$PYTHON_EXEC -m venv .venv
source .venv/bin/activate

echo "⬆️ Atualizando ferramentas de build..."
pip install --upgrade pip setuptools wheel

echo "📦 Instalando dependências..."
pip install -r requirements.txt

echo "✅ Verificando instalação..."
pip list | grep -E "(numpy|scipy|pandas|pydantic|fastapi)"

echo "🎉 Build concluído com sucesso!"
