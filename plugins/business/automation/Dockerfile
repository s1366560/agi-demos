FROM python:3.12.13-slim
WORKDIR /app
RUN python -m pip install --no-cache-dir 'APScheduler==4.0.0a6'
COPY contributions.json triggers.py ./
COPY workflow/ workflow/
COPY worker.py /app/schedule-worker
RUN chmod 0555 /app/schedule-worker
USER 65532:65532
ENTRYPOINT ["/app/schedule-worker"]
