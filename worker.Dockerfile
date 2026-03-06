FROM python:3.12-alpine

RUN apk add --no-cache ca-certificates openvpn

WORKDIR /app
COPY standalone /app/standalone

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "standalone.gluetun_picker", "probe"]
