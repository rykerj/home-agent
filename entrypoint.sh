#!/usr/bin/env bash
set -e

# 1. Fix Windows volume mount ownership error
git config --global --add safe.directory /workspace

# 2. Configure Git author identity
git config --global user.name "${GIT_AUTHOR_NAME:-Hermes Agent}"
git config --global user.email "${GIT_AUTHOR_EMAIL:-hermes-agent@://github.com}"

# 3. Configure Git, gh CLI, and Hermes .env automatically
if [ -n "$GITHUB_TOKEN" ]; then
    # Remove any old URL rewrites that might conflict
    git config --global --unset-all url."https://x-access-token:${GITHUB_TOKEN}@://github.com".insteadOf || true
    
    # Save persistent gh CLI login config to ~/.config/gh/hosts.yml
    echo "$GITHUB_TOKEN" | env -u GITHUB_TOKEN -u GH_TOKEN gh auth login --with-token
    
    # Link Git directly to gh's credential helper
    env -u GITHUB_TOKEN -u GH_TOKEN gh auth setup-git
    
    # Write both GITHUB_TOKEN and GH_TOKEN into Hermes's .env
    mkdir -p /home/hermes/.hermes
    touch /home/hermes/.hermes/.env
    
    sed -i '/^GITHUB_TOKEN=/d' /home/hermes/.hermes/.env
    sed -i '/^GH_TOKEN=/d' /home/hermes/.hermes/.env
    
    echo "GITHUB_TOKEN=${GITHUB_TOKEN}" >> /home/hermes/.hermes/.env
    echo "GH_TOKEN=${GITHUB_TOKEN}" >> /home/hermes/.hermes/.env
fi

# 4. Hand off to your container's CMD
exec "$@"
