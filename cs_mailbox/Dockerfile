# The published cs-mailbox server image, built and released from
# chrisuthe/ConnectSensors (mailbox/Dockerfile). This image is only the Home
# Assistant layer on top: the options launcher, AppArmor and the health check.
# Pinned by its multi-arch index digest, which serves amd64 and aarch64; the tag
# is for the reader. Moved by hand, like the other pins (.github/dependabot.yml).
ARG BASE=ghcr.io/chrisuthe/cs-mailbox:0.2.0@sha256:6c7f35d22847df2a6f0520a864f74820bc8798c31c4184bce4972f185261fec5
FROM ${BASE}

LABEL \
    org.opencontainers.image.title="cs-mailbox Home Assistant app" \
    org.opencontainers.image.description="ConnectSensors federation mailbox server packaged as a Home Assistant app" \
    org.opencontainers.image.source="https://github.com/chrisuthe/HAOS-cs-mailbox" \
    org.opencontainers.image.url="https://github.com/chrisuthe/HAOS-cs-mailbox" \
    org.opencontainers.image.licenses="MIT"

COPY rootfs/ /

# The base runs as the mailbox user (10001). The launcher starts as root to
# prepare /data and read /ssl, then drops to that user itself.
USER root
WORKDIR /

# Is the port accepting connections? A full handshake would need a client key,
# and would count against admission. The port is fixed, so the base's
# CS_MAILBOX_PORT is not consulted.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD ["python3", "-I", "-c", "import socket; socket.create_connection(('127.0.0.1', 8443), 5).close()"]

# Not the base's container_entry.py: the launcher builds cs-mailbox's whole
# command line, so the base's CS_MAILBOX_* variables never reach it.
ENTRYPOINT ["python3", "-I", "/usr/lib/cs-mailbox-app/launch.py"]
CMD []
