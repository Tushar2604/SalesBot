FROM node:20-alpine AS base
WORKDIR /srv
ENV NEXT_TELEMETRY_DISABLED=1

COPY package.json package-lock.json* ./

# ── dev: deps installed in the image, source bind-mounted by compose ──────────
FROM base AS dev
RUN npm install
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]

# ── build stage ───────────────────────────────────────────────────────────────
FROM base AS builder
RUN npm ci || npm install
COPY . .
RUN npm run build

# ── prod: standalone output, non-root ─────────────────────────────────────────
FROM node:20-alpine AS prod
WORKDIR /srv
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
RUN addgroup -g 10001 nodejs && adduser -u 10001 -G nodejs -S nextjs
COPY --from=builder --chown=nextjs:nodejs /srv/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /srv/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /srv/public ./public
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
