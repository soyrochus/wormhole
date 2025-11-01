# syntax=docker/dockerfile:1
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG USERNAME=pengu
ARG UID=1000
ARG GID=1000

# Base tools + ImageMagick
RUN apt-get update && apt-get install -y --no-install-recommends \
    imagemagick \
    curl wget git vim less unzip zip build-essential \
    python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user matching host UID/GID (avoids root-owned files on bind mounts)
RUN set -eux; \
    if getent passwd "${UID}" >/dev/null; then \
      existing_user="$(getent passwd "${UID}" | cut -d: -f1)"; \
      if [ "${existing_user}" != "${USERNAME}" ]; then \
        existing_group="$(id -gn "${existing_user}")"; \
        usermod -l "${USERNAME}" "${existing_user}"; \
        if [ "${existing_group}" != "${USERNAME}" ]; then \
          groupmod -n "${USERNAME}" "${existing_group}"; \
        fi; \
      fi; \
      current_home="$(getent passwd "${USERNAME}" | cut -d: -f6)"; \
      if [ "${current_home}" != "/home/${USERNAME}" ]; then \
        usermod -d "/home/${USERNAME}" -m "${USERNAME}"; \
      fi; \
    else \
      if getent group "${GID}" >/dev/null; then \
        existing_group="$(getent group "${GID}" | cut -d: -f1)"; \
        if [ "${existing_group}" != "${USERNAME}" ]; then \
          groupmod -n "${USERNAME}" "${existing_group}"; \
        fi; \
      else \
        groupadd -g "${GID}" "${USERNAME}"; \
      fi; \
      useradd -m -u "${UID}" -g "${GID}" -s /bin/bash "${USERNAME}"; \
    fi; \
    if getent group "${USERNAME}" >/dev/null; then \
      usermod -g "${USERNAME}" "${USERNAME}"; \
    fi

WORKDIR /workspace
RUN chown -R ${UID}:${GID} /workspace
USER ${USERNAME}

ENV PATH="/home/${USERNAME}/.local/bin:${PATH}"

# Default: do nothing until you exec/shell in
CMD ["bash"]
