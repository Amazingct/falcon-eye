# Falcon-Eye RTSP/ONVIF Camera Relay
FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    pip install --no-cache-dir flask onvif-zeep requests && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY app.py /app.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV RTSP_URL=""
ENV WIDTH="640"
ENV HEIGHT="480"
ENV FPS="15"
ENV CAMERA_LABEL="CAMERA"

EXPOSE 8081

ENTRYPOINT ["/entrypoint.sh"]
