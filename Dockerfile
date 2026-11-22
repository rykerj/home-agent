FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

COPY bridge/groupme-notify-skill.md /opt/hermes-skills/groupme-notify/SKILL.md

# Install system dependencies, git, tini, GitHub CLI (gh), and Tailscale.
# Tailscale gives the container a stable mesh IP on your home network so it can
# reach services served over Tailscale (dashboard, Ollama) reliably.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates tini libatomic1 gh tailscale \
    && rm -rf /var/lib/apt/lists/*


# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash hermes && \
    mkdir -p /ms-playwright /workspace /home/hermes/.hermes && \
    chown -R hermes:hermes /ms-playwright /workspace /home/hermes

# Copy entrypoint script and make it executable
COPY --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh

# Install Hermes Agent, Playwright, Chromium, and Scrapling
RUN pip install --no-cache-dir hermes-agent playwright scrapling && \
    playwright install --with-deps chromium && \
    chown -R hermes:hermes /ms-playwright

USER hermes
WORKDIR /workspace

# Pre-install the built-in GitHub skill for Hermes
RUN hermes skills install github || true

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
