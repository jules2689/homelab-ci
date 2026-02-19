# Combined orchestrator + runner: poll, clone, run job in same container (no inner Docker).
FROM python:3.12-alpine

RUN apk add --no-cache \
    git \
    ruby \
    ruby-bundler \
    ruby-dev \
    build-base \
    python3 \
    py3-pip \
    bash \
    util-linux

RUN gem install bundler --no-document 2>/dev/null || true

WORKDIR /app
COPY requirements.txt .
ENV PIP_ROOT_USER_ACTION=ignore
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x /app/run-in-repo.sh /app/entrypoint.sh

ENV PUID=0 PGID=0
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "main.py"]
