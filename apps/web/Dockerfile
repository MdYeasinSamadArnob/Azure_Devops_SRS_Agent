FROM node:20-slim AS deps
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm install

# ---- dev: hot dev server (docker-compose.yml's default target) ----
FROM node:20-slim AS dev
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web .
ENV NODE_ENV=development
EXPOSE 3000
CMD ["npm", "run", "dev"]

# ---- builder: compiles the production bundle ----
FROM node:20-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web .
ENV NEXT_TELEMETRY_DISABLED=1
# NEXT_PUBLIC_* vars are baked in at build time — passed through as build
# args so a production build can still override the default (host-derived)
# API base URL for an advanced deployment. See lib/api-base-url.ts.
ARG NEXT_PUBLIC_API_BASE_URL=""
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
RUN npm run build

# ---- prod: minimal runtime — only the standalone trace output, no
# dev dependencies, no full node_modules, no source ----
FROM node:20-slim AS prod
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
