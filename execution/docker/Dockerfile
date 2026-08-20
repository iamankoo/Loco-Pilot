# LocoPilot's default execution sandbox image.
#
# Deliberately scoped to Python — a project-specific runtime, not one
# enormous image bundling every language. A Node/Java/etc. image would be
# a sibling Dockerfile in this same directory (e.g. Dockerfile.node),
# built and referenced the same way; execution/docker/sandbox.py takes
# `image` as a parameter and has no language-specific logic at all.
FROM python:3.11-slim

# Matches the --user 1000:1000 flag Sandbox.create() always passes —
# baking the UID into the image keeps container creation self-contained.
RUN useradd --uid 1000 --create-home --shell /bin/bash sandbox

# Pinned so the image is reproducible; pytest is the only tool the Phase
# 1.4 fixture project needs. Add more build/test tooling here as later
# fixtures require it.
RUN pip install --no-cache-dir pytest==8.3.3

WORKDIR /workspace
USER sandbox

# Keeps the container alive between `docker exec` calls — the Sandbox
# lifecycle (create/start/execute/destroy) drives everything else; this
# process never runs project code itself.
CMD ["sleep", "infinity"]
