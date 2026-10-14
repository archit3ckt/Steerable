# The Steerable engine for one hosted company (Steerable Cloud). Build from the repo root:
#   docker build -f container/Dockerfile -t steerable-engine .
# The company folder lives on a volume at /company. The first start fills it from template/.
FROM python:3.12-slim

ARG CLAUDE_CODE_VERSION=latest
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends git nodejs npm tini ca-certificates tzdata \
 && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
 && npm cache clean --force \
 && rm -rf /var/lib/apt/lists/*

COPY template/requirements.txt /tmp/requirements.txt
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Chromium for website logins and the routines that use them (scripts/browser.py). The full
# browser, not Playwright's headless shell: its headless mode is the real Chrome, which sites
# treat as one. With the fonts a desktop has (pages measure them), beyond the few Chromium needs.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN /opt/venv/bin/python -m playwright install --with-deps --no-shell chromium \
 && apt-get install -y --no-install-recommends fonts-dejavu fonts-noto-core fonts-roboto fonts-open-sans \
      fonts-crosextra-carlito fonts-crosextra-caladea \
 && rm -rf /var/lib/apt/lists/* && chmod -R a+rX /opt/ms-playwright

COPY template /opt/steerable/template
COPY container/entrypoint.py /opt/steerable/entrypoint.py
# Which engine this image ships (companies update to it on start). Build with
#   --build-arg ENGINE_VERSION=$(git rev-parse --short HEAD)
ARG ENGINE_VERSION=dev
RUN echo "$ENGINE_VERSION" > /opt/steerable/VERSION

# The volume's root belongs to root (only its group is ours), and git refuses a repository in a
# folder someone else owns unless it's trusted.
RUN git config --system --add safe.directory /company

# Runs as a fixed non-root user. HOME is on the volume so Claude Code's sessions persist.
RUN useradd --uid 10001 --home-dir /company/.home --no-create-home steerable \
 && mkdir -p /company /shared && chown 10001:10001 /company /shared
# (Owned by the user here, so a new Docker volume mounted on them starts out writable.)
USER 10001
WORKDIR /company
ENV HOME=/company/.home COMPANY_DIR=/company \
    AGENT_API_HOST=0.0.0.0 AGENT_API_PORT=8787 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    GIT_AUTHOR_NAME=COO GIT_AUTHOR_EMAIL=coo@steerable.local \
    GIT_COMMITTER_NAME=COO GIT_COMMITTER_EMAIL=coo@steerable.local
EXPOSE 8787
ENTRYPOINT ["tini", "--", "python", "/opt/steerable/entrypoint.py"]
