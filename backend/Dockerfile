FROM python:3.11-slim
WORKDIR /app
RUN addgroup --gid 1001 otaki \
 && adduser --uid 1001 --gid 1001 --no-create-home --disabled-password --gecos "" otaki
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app
RUN chown -R otaki:otaki /app
USER otaki
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
