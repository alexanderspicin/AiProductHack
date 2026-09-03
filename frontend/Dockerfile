# syntax=docker/dockerfile:1.7
#
# Static build served by nginx. Both stages use images that exist for amd64 and
# arm64, so this builds natively on Apple Silicon.
#
# The backend URL is baked in at build time (Vite inlines import.meta.env), so
# it is a build arg rather than a runtime env var:
#
#   docker build --build-arg VITE_PIPECAT_BASE_URL=http://localhost:7860 .

FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY . .

ARG VITE_PIPECAT_BASE_URL=http://localhost:7860
ENV VITE_PIPECAT_BASE_URL=$VITE_PIPECAT_BASE_URL
# `npm run build` = tsc && vite build, so a type error fails the image build.
RUN npm run build

FROM nginx:alpine AS runtime

COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget --quiet --spider http://127.0.0.1/ || exit 1
