# 🐳 Docker Swarm Deployment Guide for Kronk

## Protect the Docker daemon socket

### 🔒 1. Certificate Authority (CA)

```bash
mkdir -p ~/certs/ca && cd ~/certs/ca
openssl genrsa -aes256 -out ca-key.pem 4096
openssl req -new -x509 -days 3650 -key ca-key.pem -sha256 -out ca.pem -subj "/CN=Kronk Root CA"
```

**Note:** The `ca.pem` file is the Certificate Authority certificate used to verify signed certificates.

**Warning:** The `ca-key.pem` file is the CA private key. **Store it securely** and **never store it as a Docker secret** in production to prevent unauthorized access.

### 🚀 2. Docker Daemon TLS (for Prometheus)

```bash
mkdir -p ~/certs/docker && cd ~/certs/docker

openssl genrsa -out docker-server-key.pem 4096
openssl req -new -key docker-server-key.pem -out docker-server.csr -subj "/CN=127.0.0.1"
echo "subjectAltName = IP:127.0.0.1" > docker-ext.cnf
echo "extendedKeyUsage = serverAuth" >> docker-ext.cnf
openssl x509 -req -in docker-server.csr -CA ../ca/ca.pem -CAkey ../ca/ca-key.pem -CAcreateserial -out docker-server-crt.pem -days 3650 -sha256 -extfile docker-ext.cnf

openssl genrsa -out docker-client-key.pem 4096
openssl req -new -key docker-client-key.pem -out docker-client.csr -subj "/CN=prometheus"
echo "extendedKeyUsage = clientAuth" > docker-client-ext.cnf
openssl x509 -req -in docker-client.csr -CA ../ca/ca.pem -CAkey ../ca/ca-key.pem -CAcreateserial -out docker-client-cert.pem -days 3650 -sha256 -extfile docker-client-ext.cnf

docker secret create docker_ca.pem ../ca/ca.pem
docker secret create docker_server_cert.pem docker-server-crt.pem
docker secret create docker_server_key.pem docker-server-key.pem
docker secret create docker_client_cert.pem docker-client-cert.pem
docker secret create docker_client_key.pem docker-client-key.pem
```

#### Update `/etc/docker/daemon.json`

```json
{
  "tls": true,
  "tlsverify": true,
  "tlscacert": "/etc/docker/certs/ca.pem",
  "tlscert": "/etc/docker/certs/docker-server-crt.pem",
  "tlskey": "/etc/docker/certs/docker-server-key.pem",
  "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2376"]
}
```

### Then restart Docker

```bash
sudo systemctl restart docker
```

### 📈 How Prometheus Should Connect

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

### 🔒 3. Redis and PostgreSQL TLS (shared client certs for FastAPI)

```bash
# Redis Server Certificate
mkdir -p ~/certs/redis && cd ~/certs/redis
openssl genrsa -out redis-server.key.pem 4096
openssl req -new -key redis-server.key.pem -out redis-server.csr -subj "/CN=redis.internal"
echo "subjectAltName = DNS:redis.internal" > redis-ext.cnf
echo "extendedKeyUsage = serverAuth" >> redis-ext.cnf
openssl x509 -req -in redis-server.csr -CA ../ca/ca.pem -CAkey ../ca/ca-key.pem -CAcreateserial -out redis-server.crt.pem -days 3650 -sha256 -extfile redis-ext.cnf

# PostgreSQL Server Certificate
mkdir -p ~/certs/postgres && cd ~/certs/postgres
openssl genrsa -out pg-server.key.pem 4096
openssl req -new -key pg-server.key.pem -out pg-server.csr -subj "/CN=postgres.internal"
echo "subjectAltName = DNS:postgres.internal" > pg-ext.cnf
echo "extendedKeyUsage = serverAuth" >> pg-ext.cnf
openssl x509 -req -in pg-server.csr -CA ../ca/ca.pem -CAkey ../ca/ca-key.pem -CAcreateserial -out pg-server.crt.pem -days 3650 -sha256 -extfile pg-ext.cnf

# FastAPI Client Certificate (shared for both Redis and PostgreSQL)
mkdir -p ~/certs/fastapi && cd ~/certs/fastapi
openssl genrsa -out fastapi-client-key.pem 4096
openssl req -new -key fastapi-client-key.pem -out fastapi-client.csr -subj "/CN=fastapi-client"
echo "extendedKeyUsage = clientAuth" > client-ext.cnf
openssl x509 -req -in fastapi-client.csr -CA ../ca/ca.pem -CAkey ../ca/ca-key.pem -CAcreateserial -out fastapi-client-crt.pem -days 3650 -sha256 -extfile client-ext.cnf

docker secret create fastapi_ca.pem ../ca/ca.pem
docker secret create fastapi_client_cert.pem fastapi-client-crt.pem
docker secret create fastapi_client_key.pem fastapi-client-key.pem

rediss://:password@redis.internal:6379/0?ssl_cert_reqs=required&ssl_ca_certs=/run/secrets/fastapi_ca.pem&ssl_certfile=/run/secrets/fastapi_client_cert.pem&ssl_keyfile=/run/secrets/fastapi_client_key.pem
postgresql://user:password@postgres.internal:5432/dbname?sslmode=verify-full&sslrootcert=/run/secrets/fastapi_ca.pem&sslcert=/run/secrets/fastapi_client_cert.pem&sslkey=/run/secrets/fastapi_client_key.pem
```

---

## 🔧 1. Initialize Docker Swarm

On the **manager node**:

```bash
docker swarm init --advertise-addr <MANAGER_NODE_PUBLIC_IP>
```

Get the worker token:

```bash
docker swarm join-token worker
```

Use the printed command to add worker nodes:

```bash
docker swarm join --token <TOKEN> <MANAGER_NODE_PUBLIC_IP>:2377
```

---

## 🔐 2. Create Secrets (on Manager Node)

## 🐳 Docker Secrets Creation Guide for Kronk Backend

This guide contains all the commands needed to create Docker secrets for your backend services.

## 🔐 Secrets Creation

```bash
echo './' | docker secret create pythonpath_env -

# KEYS & CERTS
docker secret create ca-cert ./ca.crt
docker secret create client-cert ./client-cert.pem
docker secret create client-key ./client-key.pem
docker secret create redis-cert ./redis-cert.pem
docker secret create redis-key ./redis-key.pem
docker secret create postgres-cert ./postgres-cert.pem
docker secret create postgres-key ./postgres-key.pem

# POSTGRES
echo 'postgresql+psycopg2://user:password@postgres:5432/dbname?sslmode=verify-full&sslrootcert=/run/secrets/ca-cert&sslcert=/run/secrets/client-cert&sslkey=/run/secrets/client-key' | docker secret create database-url -

DATABASE_URL
REDIS_URL
TASKIQ_WORKER_URL
TASKIQ_RESULT_BACKEND_URL
TASKIQ_REDIS_SCHEDULE_SOURCE_URL
SECRET_KEY
REFRESH_TOKEN_EXPIRE_TIME
ACCESS_TOKEN_EXPIRE_TIME
ALGORITHM
MINIO_BUCKET_NAME
MINIO_ENDPOINT
MINIO_ROOT_PASSWORD
MINIO_ROOT_USER
EMAIL_SERVICE_API_KEY
FIREBASE_ADMINSDK

# REDIS
echo 'rediss://207.154.199.121:redis_password@redis:6379?ssl_cert_reqs=CERT_REQUIRED&ssl_ca_certs=/run/secrets/ca-cert&ssl_certfile=/run/secrets/client-cert&ssl_keyfile=/run/secrets/client-key' | docker secret create redis-url -
echo 'redis://default:redis_password@207.154.199.121:6379/1' | docker secret create taskiq-worker-url -
echo 'redis://default:redis_password@207.154.199.121:6379/2' | docker secret create taskiq-redis_schedule_source-url -
echo 'redis://default:redis_password@207.154.199.121:6379/3' | docker secret create taskiq-scheduler-url -

# OBJECT STORAGE
echo 'kamronbek' | docker secret create minio_root_user -
secret_key=n7zzLc5yZcnXA9f/v+vIVnP3pjxkE6NDNi4CEEnTM+E

access_key_id=DO00J2BEN93Y8P6LBEYR


# FASTAPI-JWT
echo 'f94b638b565c503932b657534d1f044b7f1c8acfb76170e80851704423a49186' | docker secret create secret_key -
echo 'HS256' | docker secret create algorithm -
echo '60' | docker secret create access_token_expire_time -
echo '7' | docker secret create refresh_token_expire_time -

# EMAIL
echo 'wSsVR61z+0b3Bq9+mzWtJOc+yAxSUgv1HEx93Qaoun79Sv7KosduxECdBw/1HPBLGDNpQWAU9bN/yx0C0GUN2dh8mVAGDSiF9mqRe1U4J3x17qnvhDzIWWtYlxGNLIkLzwlumWdiEssi+g==' | docker secret create email_service_api_key -

# FIREBASE
echo 'service_account' | docker secret create firebase_type -
echo 'kronk-dev-2' | docker secret create firebase_project_id -
echo '2e8a8280dd807ef3422ae152fc72342b3a1ea8ec' | docker secret create firebase_private_key_id -
echo -e '-----BEGIN PRIVATE KEY-----\\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDZvDybrhISTiym\\nxebJ9EqAkv/BeJ4VmNNJIIoDI03JcUERjksermDq/zX2tHtisJc1ynT7mBhFtpQ3\\noAxHF3dnC5b4ZKHbhNNmSpReT1nRc8b/A98nIS5LEY01NWmGL9EitgSUSFtV2D14\\nQqZhI05C6hKVfrupEuYWko7mRHV5b5yczksXTtZSIkOP3rHs9AVFBkXe9eraS7w1\\n5DzcLf8sQo4qjpciffLqMsl2MtBsYgVx4iJyYTYKJ2meoMlolEiBqJS9J401KwoH\\n3J529JwvlFsVmcLbE5/BcCtiR8lA9MqeNfh2jtMaP/HlmcV12GYflO01ywhmegf+\\nZNie544DAgMBAAECggEAHp3tCdki2mcauULHzqsm1MiW5R4wYIoSX8yPC5zpwcNG\\nqpDPOFu97h1/+ZZsaTa6tIopA/3hn9/qHJ5JS6/djuRe0MPZzLPzRAWFsnNHBoBY\\nwaBKP0bXqx+nMw21LnTH3DErGKzKBxq2nhQFMFCWHyup/FKLUd2B9Decl32V5ULN\\nnQktoFHRowZ9jms3ZtKx+CwIt1CG0MrLpV4O2s9jcVlJC005Vjtw2HEgSPOmRnxB\\nGt3uthghBnuAqy8k2qMsCSiokvjcenAmL1rJBX4gURqSD72qL1YFPYQvlnckK7tB\\nt/bYoDFhvyuVZjoG9OwDyUVi8SH/GqxFWsBVR2yUtQKBgQDzt0oJiz9EaPXQNxnt\\nfyciVKFfdr/YXE9XInyVKXkZM+El3dXp7jWTWDtjs3uCi55AovZhmrWYa7aXxOSN\\n4O3Kh8i6jtdbpn7nYxbdEdBQhDLvntTYXkfdVROuYIUWwTl3vgRQDdmnZS8cuKyD\\n6FmRD8EhTooi/iJZAMC4sodkhQKBgQDktbbZ/Gpo0NJRg5xPz3SqTP8M5kRRw7V2\\nTu4kbkP/DGAQJ1Kx6f5Bi0W6kY/58Gri7nol0cWO6BxPmidZMLpuzKT0JqJTDQJR\\nMA8DSzEbbKFZZhTaWQKw3aIkWFeataOy5xFK4AT/BdpFs2T6zN/qQ2wsgVjOuJmv\\ntmHNAkiS5wKBgQDLJtzDSdxKBQfqMRQewV/4oP0HG3BdRM0p/+hDWhfEp1ck/l6C\\nqfrkwKZ4vDLXJdSbYnvn7lMzI45HwmsVzQnKShdLUyg3EHk2HYYAbwnrI9dloEsh\\ntK1I1NMcBv7JcfWaV702keT9QT3dPh8nsTV/0tcVEWfaNWaiNBtxmfd8FQKBgD4T\\nhDnOZSNl6m/thPO0nznKBEAAD/MRZ6Ng8Qo6U4JaXYiE49EebcBkiNyGvcldE+Xc\\nTJMPSMvs/CIu+RcgPrnsGambAtv/3+0hWjHOqtmCtpiJOIe7ORvATE4JHF4FhxT7\\n2pm0DCcb846Pjoz0JqJzAl1iDjStrikfG5SFViVpAoGBAOTGAQpaILeHRvpSUWfe\\nbOcG6decAni/RetJ0Pkc1ZfoJBP8JOxxONdUvzBO5S1uPPlpLt/rF/SpLDtcZ/D3\\nSpBMT9pCDwvxokXHwqHcDI3cMpS4IN8PxQPix2nMQ4KCmLoqsjsJEy78jyD81Ox6\\nevNMbqc8R3N75mdfHchxxdyS\\n-----END PRIVATE KEY-----' | docker secret create firebase_private_key -

echo 'firebase-adminsdk-wbkf7@kronk-dev-2.iam.gserviceaccount.com' | docker secret create firebase_client_email -
echo '110999035518165526815' | docker secret create firebase_client_id -
echo 'https://accounts.google.com/o/oauth2/auth' | docker secret create firebase_auth_uri -
echo 'https://oauth2.googleapis.com/token' | docker secret create firebase_token_uri -
echo 'https://www.googleapis.com/oauth2/v1/certs' | docker secret create firebase_auth_provider_x509_cert_uri -
echo 'https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-wbkf7%40kronk-dev-2.iam.gserviceaccount.com' | docker secret create firebase_client_cert_url -

# AZURE TRANSLATOR
echo 'UPd3xWP6AzyAcRS1Nno7YWx8vmA9Dx1gCnBrufdISHxoueeejBxoJQQJ99BAAC3pKaRXJ3w3AAAbACOG62Hd' | docker secret create azure_translator_key -
echo 'eastasia' | docker secret create azure_translator_region -
echo 'https://api.cognitive.microsofttranslator.com/translate' | docker secret create azure_translator_endpoint -

```bash
# Database URLs
 echo "postgresql+asyncpg://kamronbek:kamronbek2003@<postgres_vps_ip>:5432/<postgres_db>" | docker secret create db_url -
 echo "redis://default:<redis_password>@<redis_vps_ip>:6379" | docker secret create redis_url -

# Monitoring (Grafana)
 echo "kamronbek2003" | docker secret create gf_security_admin_password -

# Redis/Postgres credentials
 echo "kamronbek" | docker secret create postgres_user -
 echo "dev_db" | docker secret create postgres_db -
 echo "kamronbek2003" | docker secret create redis_password -

# Traefik Admin UI
 echo "kamronbek" | docker secret create traefik_username -
 echo "kamronbek2003" | docker secret create traefik_password -

# Traefik Auth (hashed password)
 echo "$(htpasswd -nB kamronbek)" | docker secret create traefik_auth -
 echo "$(htpasswd -nbB kamronbek kamronbek2003)" | docker secret create traefik_user_credentials -
```

---

## 🌐 3. Create Overlay Network

```bash
docker network create --driver=overlay --attachable traefik-public
```

---

## 🔒 4. Set Permissions on ACME File (TLS Certs)

```bash
chmod 600 cluster/swarm/traefik/config/acme.json
```

---

## 📦 5. Deploying Services (From Your Local Machine)

Ensure you are using the right context:

```bash
docker context use dev-kronk
```

### 🛡️ Traefik

```bash
docker stack deploy -c cluster/swarm/traefik/traefik.yml traefik-stack
```

### 🧠 Backend

```bash
docker stack deploy -c cluster/swarm/backend/backend_stack.yml backend-stack
```

### 📊 Monitoring

```bash
docker stack deploy -c cluster/swarm/monitoring/portainer.yml monitoring-stack
```

Add others similarly:

```bash
docker stack deploy -c cluster/swarm/monitoring/grafana.yml monitoring-stack
```
