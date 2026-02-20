FROM python:3.12-alpine
RUN apk add --no-cache util-linux \
    && pip install --no-cache-dir --upgrade pip
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py entrypoint.sh github_app.py github_api.py .
RUN chmod +x /app/entrypoint.sh
ENV CI_LITE_WEB_PORT=8080
ENV PUID=0 PGID=0
EXPOSE 8080
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "server.py"]
