# Stage 1: nginx base to copy binary and config
FROM nginx:1.27-alpine AS base

# Stage 2: distroless static — serve HTML with nginx
FROM nginx:1.27-alpine
COPY index.html /usr/share/nginx/html/index.html
RUN rm -f /usr/share/nginx/html/index.nginx-debian.html

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
