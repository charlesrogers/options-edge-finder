FROM node:20-alpine AS base

FROM base AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG CACHEBUST=1
# No Supabase build args any more. Nothing in the browser talks to Supabase —
# the two client components that reference it import row TYPES, which are erased
# at compile time — so the anon key no longer needs to be inlined into the
# bundle, and the service-role key must never be: build args are baked into
# image layers and readable by anyone who pulls the image. The server reads
# SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from Coolify runtime env instead.
RUN npm run build

FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
USER nextjs
EXPOSE 3000
ENV PORT=3000
CMD ["npm", "run", "start"]
