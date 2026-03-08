FROM python:3.12-alpine

RUN apk add --no-cache ca-certificates openvpn

WORKDIR /app
COPY gluetun_picker /app/gluetun_picker

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "gluetun_picker", "probe"]
