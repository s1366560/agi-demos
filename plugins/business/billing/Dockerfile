FROM python:3.12-alpine
WORKDIR /app
COPY workers/invoice_contract.py workers/invoice_terms.json invoice_record.py plans.json contributions.json ./
COPY workers/invoice_worker.py /app/invoice-worker
RUN chmod 0555 /app/invoice-worker && ln /app/invoice-worker /app/invoice-worker-with-plan-service
USER 65532:65532
ENTRYPOINT ["/app/invoice-worker"]
