# Build stage
FROM node:22-alpine AS builder

WORKDIR /app/web

# Copy package files
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./

# Install dependencies with the version pinned in package.json
RUN --mount=type=cache,id=memstack-web-pnpm,target=/pnpm/store \
    corepack enable && corepack pnpm install --frozen-lockfile --store-dir /pnpm/store

# Copy source code
COPY web ./
COPY agi-stack/packages/plugin-runtime /app/agi-stack/packages/plugin-runtime
COPY agi-stack/packages/plugin-slots /app/agi-stack/packages/plugin-slots
COPY agi-stack/packages/plugin-marketplace-ui /app/agi-stack/packages/plugin-marketplace-ui
COPY sdk/memstack-plugin-sdk/src/slotUi.ts /app/sdk/memstack-plugin-sdk/src/slotUi.ts

# Build the application
RUN corepack pnpm run build

# Production stage
FROM nginx:alpine

# Copy built files from builder
COPY --from=builder /app/web/dist /usr/share/nginx/html

# Copy nginx configuration
COPY web/nginx.conf /etc/nginx/conf.d/default.conf

# Expose port 80
EXPOSE 80

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
