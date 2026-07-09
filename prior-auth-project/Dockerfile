FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir ".[web]"

COPY dataset ./dataset
COPY level1_prior_auth.py ./
RUN mkdir -p logs

EXPOSE 8000

CMD ["uvicorn", "prior_auth.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
