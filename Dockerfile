FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e .
EXPOSE 8000
CMD ["sh", "-c", "echo '>> alembic upgrade head'; alembic upgrade head && echo '>> launching uvicorn on port '${PORT:-8000}; exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
