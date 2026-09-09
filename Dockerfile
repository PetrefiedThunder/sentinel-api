FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4
ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e .
EXPOSE 8000
CMD ["sh", "-c", "echo '>> alembic upgrade head'; alembic upgrade head && echo '>> launching uvicorn on port '${PORT:-8000}; exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
