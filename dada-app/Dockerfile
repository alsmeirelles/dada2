FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
ARG VITE_API_BASE_URL
ARG VITE_REALTIME_URL
ARG VITE_UPLOAD_CHUNK_BYTES=8388608
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_REALTIME_URL=${VITE_REALTIME_URL}
ENV VITE_UPLOAD_CHUNK_BYTES=${VITE_UPLOAD_CHUNK_BYTES}
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html
RUN chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx /var/run

USER nginx
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
