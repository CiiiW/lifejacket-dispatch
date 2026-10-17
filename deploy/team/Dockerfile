FROM nginx:stable-alpine

COPY check-token.sh /docker-entrypoint.d/19-check-token.sh
COPY edge.conf.template /etc/nginx/templates/default.conf.template
RUN chmod +x /docker-entrypoint.d/19-check-token.sh

# Substitute deployment settings while preserving nginx's own $variables.
ENV NGINX_ENVSUBST_FILTER="^(ORIGIN_TOKEN|ORIGIN_URL)$"
EXPOSE 8080
