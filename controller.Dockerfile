FROM python:3.12-alpine

RUN apk add --no-cache docker-cli

WORKDIR /app
COPY gluetun_picker /app/gluetun_picker
COPY worker.Dockerfile /app/worker.Dockerfile

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "gluetun_picker"]
