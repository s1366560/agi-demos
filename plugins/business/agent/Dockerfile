FROM python:3.12.13-slim
WORKDIR /publisher
COPY pyproject.toml __init__.py worker.py react_loop.py turn.py release.py package.json contributions.json ./
COPY ui/settings.json ui/skill.js ui/chat-web.js ui/chat-web.css ui/chat-desktop.js ui/chat-desktop.css ./ui/
COPY engine ./engine
COPY backend ./backend
COPY skill_validation ./skill_validation
COPY execution_statistics ./execution_statistics
RUN python -m pip install --no-cache-dir '.[worker]'
USER 65532:65532
ENTRYPOINT ["/usr/local/bin/memstack-agent-worker"]
