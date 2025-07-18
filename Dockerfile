# <� AI �` ܬt0 Dockerfile
FROM python:3.11-slim

# �� 	�� $
WORKDIR /app

# ܤ\ �pt�  D�\ (�� $X
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python Xt1 $X
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# `� tX T� ��
COPY . .

# `� tX ��� �1 (�H)
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# � x�
EXPOSE 8003

# X� �
ENV PYTHONPATH=/app
ENV OLLAMA_API_URL=http://host.docker.internal:11434

# 줴l
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8003/api/status || exit 1

# `� tX �
CMD ["python3", "final_web_app.py"]