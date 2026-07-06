FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY blob_helper ./blob_helper
RUN cd blob_helper && npm install --omit=dev

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

CMD ["python", "-m", "worker.main"]
