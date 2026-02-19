# Lightweight CI runner: Ruby + Python, pip, bundler. Deps installed at runtime.
FROM alpine:3.19

RUN apk add --no-cache \
    git \
    ruby \
    ruby-bundler \
    ruby-dev \
    build-base \
    python3 \
    py3-pip \
    bash

# Alpine 3.19: ruby 3.3, python 3.12
RUN gem install bundler --no-document 2>/dev/null || true

WORKDIR /workspace

# Entrypoint: install deps from repo then run given command
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
