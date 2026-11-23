FROM python:3.12-alpine
WORKDIR /app
COPY worker.py /app/project
COPY contributions.json /app/contributions.json
RUN chmod 0555 /app/project
USER 65532:65532
ENTRYPOINT ["/app/project"]
