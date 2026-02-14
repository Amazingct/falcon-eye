# Falcon-Eye USB Camera (Motion-based)
FROM ubuntu:22.04

RUN apt-get update && \
    apt-get install -y --no-install-recommends motion && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Default config will be overwritten at runtime
COPY motion.conf /etc/motion/motion.conf

EXPOSE 8081 8080

CMD ["motion", "-c", "/etc/motion/motion.conf"]
