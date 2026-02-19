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
    bash

RUN gem install bundler --no-document 2>/dev/null || true

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x /app/run-in-repo.sh

CMD ["python", "main.py"]
