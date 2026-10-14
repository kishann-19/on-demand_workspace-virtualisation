FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && useradd --uid 1000 --create-home --shell /bin/bash learner \
    && mkdir /workspace && chown learner:learner /workspace
COPY --chmod=0555 agent.py /opt/cloudlab/agent.py
ENV HOME=/workspace TERM=xterm-256color PYTHONDONTWRITEBYTECODE=1
WORKDIR /workspace
USER 1000:1000
CMD ["sleep", "infinity"]
