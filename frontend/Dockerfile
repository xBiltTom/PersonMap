# =====================================================================
# PersonMap — Frontend Dockerfile
# Multi-stage: build con Node 20 + pnpm, runtime con Next.js standalone.
# =====================================================================

# --- Stage 1: deps ---
FROM node:20-alpine AS deps

# pnpm como gestor de paquetes (fijado en package.json)
RUN corepack enable && corepack prepare pnpm@11.5.2 --activate

WORKDIR /app

# Solo los manifiestos primero → caché de capa de dependencias
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

# --- Stage 2: builder ---
FROM node:20-alpine AS builder

RUN corepack enable && corepack prepare pnpm@11.5.2 --activate

WORKDIR /app

# Copia node_modules desde el stage de deps
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Next.js standalone para una imagen runtime mínima (sin node_modules completos)
ARG NEXT_PUBLIC_API_URL="http://localhost:8000/api/v1"
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

# --- Stage 3: runtime ---
FROM node:20-alpine AS runtime

LABEL org.opencontainers.image.title="PersonMap Frontend"
LABEL org.opencontainers.image.description="OSINT footprint audit platform — Next.js frontend"

RUN addgroup --system nextjs && adduser --system --ingroup nextjs nextjs

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000

# Copia los artefactos mínimos del output de Next.js
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
