FROM python:3.12-alpine
WORKDIR /app
COPY mcp_server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY mcp_server ./mcp_server
ENV CI_LITE_DB=/data/runs.db
ENV CI_LITE_MCP_HOST=0.0.0.0
ENV CI_LITE_MCP_PORT=8090
EXPOSE 8090
CMD ["python", "-m", "mcp_server.server"]
