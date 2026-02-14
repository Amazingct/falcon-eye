# Build stage
FROM node:20-alpine as builder

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy source
COPY . .

# Build
RUN npm run build

# Production stage
FROM nginx:alpine

# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx config template
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Default API URL (can be overridden by env var)
ENV API_URL=http://falcon-eye-api:8000

# Expose port
EXPOSE 80

# nginx:alpine automatically runs envsubst on /etc/nginx/templates/*.template
# and outputs to /etc/nginx/conf.d/
CMD ["nginx", "-g", "daemon off;"]
