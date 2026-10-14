# The self-hosted dashboard. Built by the repo's docker-compose.yml, or:
#   docker build -t steerable-dashboard dashboard/
FROM node:24-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1 NEXT_OUTPUT=standalone
RUN npx next build

FROM node:24-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3100 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
# The same user as the engine's container, so it can read the token the engine shares.
RUN useradd --uid 10001 --no-create-home steerable && mkdir /shared && chown 10001:10001 /shared
USER 10001
EXPOSE 3100
CMD ["node", "server.js"]
