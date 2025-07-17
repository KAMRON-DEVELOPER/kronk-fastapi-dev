# 🐳 Docker Swarm Deployment Guide for Kronk

## TLS

> **Note**: The `ca.pem` file is the Certificate Authority certificate used to verify signed certificates.
>
> **Warning**: The `ca-key.pem` file is the CA private key. **Store it securely** and **never store it as a Docker secret** in production.

```bash
# **************** 1. 🔐 Certificate Authority (CA) ****************
mkdir -p ~/certs/ca && cd ~/certs/ca
openssl genrsa -aes256 -out ca-key.pem 4096
openssl req -new -x509 -days 3650 -key ca-key.pem -sha256 -out ca.pem -subj "/CN=Kronk Root CA"




# **************** 2. 🔐 Docker Daemon TLS (for Prometheus) ****************
# Server certificate
mkdir -p ~/certs/docker && cd ~/certs/docker
openssl genrsa -out docker-server-key.pem 4096
openssl req -new -key docker-server-key.pem -out docker-server.csr -subj "/CN=127.0.0.1"
echo "subjectAltName = DNS:localhost,IP:127.0.0.1" > docker-ext.cnf
echo "extendedKeyUsage = serverAuth" >> docker-ext.cnf
openssl x509 -req -in docker-server.csr -CA ../ca/ca.pem -CAkey ../ca/ca-key.pem -CAcreateserial -out docker-server-cert.pem -days 3650 -sha256 -extfile docker-ext.cnf

# Client certificate
openssl genrsa -out docker-client-key.pem 4096
openssl req -new -key docker-client-key.pem -out docker-client.csr -subj "/CN=prometheus"
echo "extendedKeyUsage = clientAuth" > docker-client-ext.cnf
openssl x509 -req -in docker-client.csr -CA ../ca/ca.pem -CAkey ../ca/ca-key.pem -CAcreateserial -out docker-client-cert.pem -days 3650 -sha256 -extfile docker-client-ext.cnf

# Create Docker secrets
cd ~/certs/docker
docker secret create docker_ca.pem ../ca/ca.pem
docker secret create docker_server_cert.pem docker-server-cert.pem
docker secret create docker_server_key.pem docker-server-key.pem
docker secret create docker_client_cert.pem docker-client-cert.pem
docker secret create docker_client_key.pem docker-client-key.pem




# **************** 3. 🔐 Redis and PostgreSQL TLS (for FastAPI) ****************

# Redis Prod
mkdir -p ~/certs/redis && cd ~/certs/redis
openssl genrsa -out redis-server-key.pem 4096
openssl req -new -key redis-server-key.pem -out redis-server-prod.csr -subj "/CN=redis.kronk.uz"
echo "subjectAltName = DNS:redis.kronk.uz" > redis-ext-prod.cnf
echo "extendedKeyUsage = serverAuth" >> redis-ext-prod.cnf
openssl x509 -req -in redis-server-prod.csr -CA ../ca/ca.pem -CAkey ../ca/ca-key.pem -CAcreateserial -out redis-server-prod-cert.pem -days 3650 -sha256 -extfile redis-ext-prod.cnf

# Redis Dev
openssl req -new -key redis-server-key.pem -out redis-server-dev.csr -subj "/CN=127.0.0.1"
echo "subjectAltName = DNS:localhost,IP:127.0.0.1" > redis-ext-dev.cnf
echo "extendedKeyUsage = serverAuth" >> redis-ext-dev.cnf
openssl x509 -req -in redis-server-dev.csr -CA ../ca/ca.pem -CAkey ../ca/ca-key.pem -CAcreateserial -out redis-server-dev-cert.pem -days 3650 -sha256 -extfile redis-ext-dev.cnf

# PostgreSQL Prod
mkdir -p ~/certs/postgres && cd ~/certs/postgres
openssl genrsa -out pg-server-key.pem 4096
openssl req -new -key pg-server-key.pem -out pg-server-prod.csr -subj "/CN=postgres.kronk.uz"
echo "subjectAltName = DNS:postgres.kronk.uz" > pg-ext-prod.cnf
echo "extendedKeyUsage = serverAuth" >> pg-ext-prod.cnf
openssl x509 -req -in pg-server-prod.csr -CA ../ca/ca.pem -CAkey ../ca/ca-key.pem -CAcreateserial -out pg-server-prod-cert.pem -days 3650 -sha256 -extfile pg-ext-prod.cnf

# PostgreSQL Dev
openssl req -new -key pg-server-key.pem -out pg-server-dev.csr -subj "/CN=127.0.0.1"
echo "subjectAltName = DNS:localhost,IP:127.0.0.1" > pg-ext-dev.cnf
echo "extendedKeyUsage = serverAuth" >> pg-ext-dev.cnf
openssl x509 -req -in pg-server-dev.csr -CA ../ca/ca.pem -CAkey ../ca/ca-key.pem -CAcreateserial -out pg-server-dev-cert.pem -days 3650 -sha256 -extfile pg-ext-dev.cnf

# FastAPI Client (shared for Redis and PostgreSQL)
mkdir -p ~/certs/fastapi && cd ~/certs/fastapi
openssl genrsa -out fastapi-client-key.pem 4096
openssl req -new -key fastapi-client-key.pem -out fastapi-client.csr -subj "/CN=fastapi"
echo "extendedKeyUsage = clientAuth" > client-ext.cnf
openssl x509 -req -in fastapi-client.csr -CA ../ca/ca.pem -CAkey ../ca/ca-key.pem -CAcreateserial -out fastapi-client-cert.pem -days 3650 -sha256 -extfile client-ext.cnf
```

---
---

## Small Configurations & Usage Guide

### Copy apropriate files like this

```bash
sudo mkdir -p /etc/docker/certs
sudo cp ~/certs/docker/docker-server-cert.pem /etc/docker/certs/
sudo cp ~/certs/docker/docker-server-key.pem /etc/docker/certs/
sudo cp ~/certs/ca/ca.pem /etc/docker/certs/
```

### Update `/etc/docker/daemon.json`

```json
{
  "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2376"],
  "tls": true,
  "tlsverify": true,
  "tlscacert": "/etc/docker/certs/ca.pem",
  "tlscert": "/etc/docker/certs/docker-server-cert.pem",
  "tlskey": "/etc/docker/certs/docker-server-key.pem"
}
```

### Restart Docker

```bash
sudo systemctl restart docker
```

### Prometheus Docker TLS Configuration

```yaml
scrape_configs:
  - job_name: 'docker-swarm'
    dockerswarm_sd_configs:
      - host: "tcp://docker-api.kronk.uz:2376"
        role: manager
        tls_config:
          ca_file: /run/secrets/ca.pem
          cert_file: /run/secrets/client-cert.pem
          key_file: /run/secrets/client-key.pem
    scheme: https
```

---
---

## 🔧 Local Development Secret Setup

> For FastAPI to run locally with secrets, it expects files at `/run/secrets/`. Docker secrets do **not** appear there during development - you must simulate them.

### 📁 Create Local `/run/secrets` Directory

```bash
sudo mkdir -p /run/secrets
```

### 🔑 Populate Dummy Secrets for Development

You can link or copy secrets manually:

```bash
# POSTGRES
echo "kronk_db" | docker secret create POSTGRES_DB -
echo "kamronbek" | docker secret create POSTGRES_USER -
echo "kamronbek2003" | docker secret create POSTGRES_PASSWORD -
echo "postgresql+asyncpg://kamronbek:kamronbek2003@localhost:5432/kronk_db?ssl=verify-full&slrootcert=/run/secrets/ca.pem&sslcert=/run/secrets/fastapi_client_cert.crt&sslkey=/run/secrets/fastapi_client_key.pem" | sudo tee /run/secrets/DATABASE_URL

# REDIS for fastapi & uvicorn
echo "default" | sudo tee /run/secrets/REDIS_USER
echo "kamronbek2003" | sudo tee /run/secrets/REDIS_PASSWORD
echo "localhost" | sudo tee /run/secrets/REDIS_HOST

# REDIS for local compose
echo "default" | docker secret create REDIS_USER -
echo "kamronbek2003" | docker secret create REDIS_PASSWORD -
echo "localhost" | docker secret create REDIS_HOST -

# Firebase
cp ./secrets/firebase-adminsdk.json /run/secrets/FIREBASE_ADMINSDK

echo "https://fra1.digitaloceanspaces.com" | sudo tee /run/secrets/S3_ENDPOINT
echo "DO00J2BEN93Y8P6LBEYR" | sudo tee /run/secrets/S3_ACCESS_KEY_ID
echo "n7zzLc5yZcnXA9f/v+vIVnP3pjxkE6NDNi4CEEnTM+E" | sudo tee /run/secrets/S3_SECRET_KEY
echo "kronk-bucket" | sudo tee /run/secrets/S3_BUCKET_NAME

# FASTAPI-JWT
echo "f94b638b565c503932b657534d1f044b7f1c8acfb76170e80851704423a49186" | sudo tee /run/secrets/SECRET_KEY

# EMAIL
echo "wSsVR61z+0b3Bq9+mzWtJOc+yAxSUgv1HEx93Qaoun79Sv7KosduxECdBw/1HPBLGDNpQWAU9bN/yx0C0GUN2dh8mVAGDSiF9mqRe1U4J3x17qnvhDzIWWtYlxGNLIkLzwlumWdiEssi+g==" |sudo tee /run/secrets/EMAIL_SERVICE_API_KEY
```

---
---

## 4. 🔑 Docker Secrets Creation

### 🐳 On VPS Manager (only secrets needed by fastapi)

```bash
# for prometheus & fastapi
docker secret create ca.pem certs/ca/ca.pem
docker secret create docker_client_cert.pem certs/docker/docker-client-cert.pem
docker secret create docker_client_key.pem certs/docker/docker-client-key.pem

docker secret create fastapi_client_cert.pem certs/fastapi/fastapi-client-cert.pem
docker secret create fastapi_client_key.pem certs/fastapi/fastapi-client-key.pem

# POSTGRES
echo "postgresql+asyncpg://kamronbek:kamronbek2003@localhost:5432/kronk_db?ssl=verify-full&sslrootcert=/run/secrets/ca.pem&sslcert=/run/secrets/fastapi_client_cert.crt&sslkey=/run/secrets/fastapi_client_key.pem" | docker secret create DATABASE_URL -

# REDIS
echo "default" | docker secret create REDIS_USER -
echo "kamronbek2003" | docker secret create REDIS_PASSWORD -
echo "localhost" | docker secret create REDIS_HOST -

# Firebase
docker secret create FIREBASE_ADMINSDK firebase-adminsdk.json

# S3 -
echo "https://fra1.digitaloceanspaces.com" | docker secret create S3_ENDPOINT -
echo "DO00J2BEN93Y8P6LBEYR" | docker secret create S3_ACCESS_KEY_ID -
echo "n7zzLc5yZcnXA9f/v+vIVnP3pjxkE6NDNi4CEEnTM+E" | docker secret create S3_SECRET_KEY -
echo "kronk-bucket" | docker secret create S3_BUCKET_NAME -

# FASTAPI-JWT
echo "f94b638b565c503932b657534d1f044b7f1c8acfb76170e80851704423a49186" | docker secret create SECRET_KEY -

# EMAIL
echo "wSsVR61z+0b3Bq9+mzWtJOc+yAxSUgv1HEx93Qaoun79Sv7KosduxECdBw/1HPBLGDNpQWAU9bN/yx0C0GUN2dh8mVAGDSiF9mqRe1U4J3x17qnvhDzIWWtYlxGNLIkLzwlumWdiEssi+g==" | docker secret create EMAIL_SERVICE_API_KEY -
```

### 🐳 On VPS with Redis & PostgreSQL (Prod Swarm Node)

```bash
# for redis & postgres
docker secret create ca.pem certs/ca/ca.pem
docker secret create redis_server_cert.pem certs/redis/redis-server-prod-cert.pem
docker secret create redis_server_key.pem certs/redis/redis-server-key.pem
docker secret create pg_server_cert.pem certs/postgres/pg-server-prod-cert.pem
docker secret create pg_server_key.pem certs/postgres/pg-server-key.pem

# POSTGRES
echo "kronk_db" | docker secret create POSTGRES_DB -
echo "kamronbek" | docker secret create POSTGRES_USER -
echo "kamronbek2003" | docker secret create POSTGRES_PASSWORD -

# REDIS
echo "default" | docker secret create REDIS_USER -
echo "kamronbek2003" | docker secret create REDIS_PASSWORD -
echo "localhost" | docker secret create REDIS_HOST -
```

---
---

## 5. 🔧 Initialize Docker Swarm

```bash
docker swarm init --advertise-addr <MANAGER_NODE_PUBLIC_IP>
docker swarm join-token worker
docker swarm join --token <TOKEN> <MANAGER_NODE_PUBLIC_IP>:2377
```

## 6. 🌐 Create Overlay Network

```bash
docker network create --driver=overlay --attachable traefik-public
```

## 7. 🔐 Set Permissions on ACME File

```bash
chmod 600 cluster/swarm/traefik/config/acme.json
```

## 8. 📆 Deploy Services

```bash
docker context use dev-kronk

docker stack deploy -c cluster/swarm/traefik/traefik.yml traefik-stack
docker stack deploy -c cluster/swarm/backend/backend_stack.yml backend-stack
docker stack deploy -c cluster/swarm/monitoring/portainer.yml monitoring-stack
docker stack deploy -c cluster/swarm/monitoring/grafana.yml monitoring-stack
```
