FROM node:20-alpine AS build

WORKDIR /app
COPY package.json /app/package.json
RUN npm install

COPY . /app
RUN npm run build

FROM nginx:1.27-alpine

ENV BACKEND_UPSTREAM=backend:8000
ENV NGINX_ENVSUBST_FILTER=BACKEND_UPSTREAM

COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
