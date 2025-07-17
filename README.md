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
# Example values — replace with your local settings

echo "get from .env" | sudo tee /run/secrets/DATABASE_URL

echo "rediss://default:kamronbek2003@localhost:6379/0" | sudo tee /run/secrets/REDIS_URL

# Taskiq URLs
sudo tee /run/secrets/TASKIQ_WORKER_URL <<< "redis://localhost:6379/0"
sudo tee /run/secrets/TASKIQ_REDIS_SCHEDULE_SOURCE_URL <<< "redis://localhost:6379/1"
sudo tee /run/secrets/TASKIQ_RESULT_BACKEND_URL <<< "redis://localhost:6379/2"

# Firebase
cp ./secrets/firebase-adminsdk.json /run/secrets/FIREBASE_ADMINSDK

# S3
sudo tee /run/secrets/S3_ENDPOINT <<< "https://s3.local"
sudo tee /run/secrets/S3_ACCESS_KEY_ID <<< "local_access_key"
sudo tee /run/secrets/S3_SECRET_KEY <<< "local_secret_key"
sudo tee /run/secrets/S3_BUCKET_NAME <<< "kronk-local"

# JWT
sudo tee /run/secrets/SECRET_KEY <<< "mysecret"

# Email API Key
sudo tee /run/secrets/EMAIL_SERVICE_API_KEY <<< "dummy-sendgrid-api-key"
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

DATABASE_URL
REDIS_URL
TASKIQ_WORKER_URL
TASKIQ_RESULT_BACKEND_URL
TASKIQ_REDIS_SCHEDULE_SOURCE_URL
FIREBASE_ADMINSDK
S3_ENDPOINT
S3_ACCESS_KEY_ID
S3_SECRET_KEY
S3_BUCKET_NAME
SECRET_KEY
EMAIL_SERVICE_API_KEY
```

### 🐳 On VPS with Redis & PostgreSQL (Prod Swarm Node)

```bash
# for redis & postgres
docker secret create ca.pem certs/ca/ca.pem
docker secret create redis_server_cert.pem certs/redis/redis-server-prod-cert.pem
docker secret create redis_server_key.pem certs/redis/redis-server-key.pem
docker secret create pg_server_cert.pem certs/postgres/pg-server-prod-cert.pem
docker secret create pg_server_key.pem certs/postgres/pg-server-key.pem
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
