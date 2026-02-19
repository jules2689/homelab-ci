FROM python:3.12-alpine
WORKDIR /app
COPY server.py .
ENV CI_LITE_WEB_PORT=8080
EXPOSE 8080
CMD ["python", "server.py"]
