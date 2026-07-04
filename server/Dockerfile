FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . 2>/dev/null || true

COPY . .
RUN pip install --no-cache-dir -e .[dev]

EXPOSE 8000
CMD ["uvicorn", "layoverlab.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
