FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/simulator

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config ./config

RUN mkdir -p /data

EXPOSE 8080

CMD ["python", "-m", "app.main"]
