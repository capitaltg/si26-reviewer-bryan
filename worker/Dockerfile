# Phase 2 adds LibreOffice + PyMuPDF system deps to this image.
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
CMD ["python", "-m", "worker.main"]
