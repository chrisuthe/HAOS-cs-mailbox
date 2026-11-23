# python:3.13-slim rather than Home Assistant's base-python: the app needs no
# s6-overlay or bashio (the launcher is Python, and config.yaml has init: false),
# cryptography and websockets install as prebuilt manylinux wheels, and the one
# multi-arch digest below serves both amd64 and aarch64. It also keeps the image
# usable as a plain container. The tag beside the digest is for the reader.
ARG BASE=docker.io/library/python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

# git is needed only to fetch cs-mailbox, so it stays in this stage.
FROM ${BASE} AS wheels
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip wheel --no-cache-dir --disable-pip-version-check --wheel-dir /wheels -r /tmp/requirements.txt

FROM ${BASE}

LABEL \
    org.opencontainers.image.title="cs-mailbox Home Assistant app" \
    org.opencontainers.image.description="ConnectSensors federation mailbox server packaged as a Home Assistant app" \
    org.opencontainers.image.source="https://github.com/chrisuthe/HAOS-cs-mailbox" \
    org.opencontainers.image.licenses="MIT"

RUN --mount=type=bind,from=wheels,source=/wheels,target=/wheels \
    pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore --no-index --find-links /wheels /wheels/*.whl \
    && groupadd --gid 10001 mailbox \
    && useradd --uid 10001 --gid 10001 --no-create-home \
        --home-dir /nonexistent --shell /usr/sbin/nologin mailbox

COPY rootfs/ /

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8443

# Is the port accepting connections? A full handshake would need a client key,
# and would count against admission.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD ["python3", "-I", "-c", "import socket; socket.create_connection(('127.0.0.1', 8443), 5).close()"]

ENTRYPOINT ["python3", "-I", "/usr/lib/cs-mailbox-app/launch.py"]
