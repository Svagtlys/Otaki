FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:alpine

# Copy files and ensure they are world-readable (755 for dirs, 644 for files)
COPY --from=build /app/dist /usr/share/nginx/html

# Switch to root briefly to fix permissions for ANY future user
USER root
RUN chmod -R 755 /usr/share/nginx/html && \
    chown -R root:root /usr/share/nginx/html
    
# Switch back to the default unprivileged user (uid 101)
# The Compose file 'user:' directive will override this at runtime
USER 101

EXPOSE 8080
