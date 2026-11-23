FROM python:3.12-alpine
WORKDIR /app
COPY backend/cluster_health.py backend/cluster_health.py
COPY sandbox-mcp-server/src/tools/text_patch.py .
COPY contributions.json .
COPY worker.py /app/worker
RUN chmod 0555 /app/worker
USER 65532:65532
ENTRYPOINT ["/app/worker"]
