# 🐳 Docker Swarm Deployment Guide for Kronk

## Protect the Docker daemon socket

### 1. Generate CA (you’ll need to enter a passphrase)

```bash
openssl genrsa -aes256 -out ca-key.pem 4096
openssl req -new -x509 -days 365 -key ca-key.pem -sha256 -out ca.pem -subj "/CN=docker-ca.kronk.uz"
```

### 2. Generate Server key and CSR

```bash
openssl genrsa -out server-key.pem 4096
openssl req -new -sha256 -key server-key.pem -out server.csr \
  -subj "/CN=docker-api.kronk.uz"
```

### 3. Create extfile for IP/DNS SANs

```bash
cat > extfile.cnf <<EOF
subjectAltName = DNS:docker-api.kronk.uz,IP:64.226.85.243,IP:127.0.0.1
extendedKeyUsage = serverAuth
EOF
```

### 4. Sign server cert

```bash
openssl x509 -req -days 365 -sha256 -in server.csr -CA ca.pem -CAkey ca-key.pem \
  -CAcreateserial -out server-cert.pem -extfile extfile.cnf
```

### 5. Generate Client key and CSR

```bash
openssl genrsa -out client-key.pem 4096
openssl req -new -sha256 -key client-key.pem -out client.csr \
  -subj "/CN=prometheus"
```

### 6. Create extfile for client

```bash
echo extendedKeyUsage = clientAuth > extfile-client.cnf
```

### 7. Sign client cert

```bash
openssl x509 -req -days 365 -sha256 -in client.csr -CA ca.pem -CAkey ca-key.pem \
  -CAcreateserial -out client-cert.pem -extfile extfile-client.cnf
```

### 8. Clean up temporary files

```bash
rm -v server.csr client.csr extfile.cnf extfile-client.cnf
```

### 9. Secure permissions

```bash
chmod 0400 ca-key.pem server-key.pem client-key.pem
chmod 0444 ca.pem server-cert.pem client-cert.pem
```

## 🔧 How to Start Docker Daemon with TLS

### In ```/etc/docker/daemon.json```

```json
{
  "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2376"],
  "tls": true,
  "tlsverify": true,
  "tlscacert": "/etc/docker/certs/ca.pem",
  "tlscert": "/etc/docker/certs/server-cert.pem",
  "tlskey": "/etc/docker/certs/server-key.pem"
}

```

### Then restart Docker

```bash
sudo systemctl restart docker
```

## 📈 How Prometheus Should Connect

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

## 🗂️ General Layout

### [ Manager Node ]

- Traefik (Ingress Controller)
- Grafana (Dashboard)
- Prometheus (Metrics DB)
- Loki (Logs DB)

### [ Worker Nodes ]

- FastAPI App Containers
- node-exporter (System metrics)
- cAdvisor (Container metrics)
- promtail (Log shipping)

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

# POSTGRES
echo 'postgresql+asyncpg://kamronbek:kamronbek2003@94.136.191.25:5432/dev_db' | docker secret create database_url -

# REDIS
echo 'redis://default:kamronbek2003@94.136.191.25:6379' | docker secret create redis_url -
echo 'redis://default:kamronbek2003@94.136.191.25:6379/0?decode_responses=True&protocol=3' | docker secret create redis_url_old -
echo 'redis://default:kamronbek2003@94.136.191.25:6379/1' | docker secret create taskiq_worker_url -
echo 'redis://default:kamronbek2003@94.136.191.25:6379/2' | docker secret create taskiq_redis_schedule_source_url -
echo 'redis://default:kamronbek2003@94.136.191.25:6379/3' | docker secret create taskiq_scheduler_url -

# MINIO
echo 'kamronbek' | docker secret create minio_root_user -
echo 'kamronbek2003' | docker secret create minio_root_password -
echo '94.136.191.25:9000' | docker secret create minio_endpoint -
echo 'dev-bucket' | docker secret create minio_bucket_name -

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

---

## 🧪 6. Useful Commands

- List stacks:

  ```bash
  docker stack ls
  ```

- List services:

  ```bash
  docker service ls
  ```

- Remove a service:

  ```bash
  docker service rm <SERVICE_ID>
  ```

- Check nodes:

  ```bash
  docker node ls
  ```

- Check logs:

  ```bash
  docker service logs <SERVICE_NAME>
  ```

- Run a test service:

  ```bash
  docker service create --replicas 2 -p 80:80 nginx
  ```

---

## 🌍 7. Access Services via Subdomains (Traefik)

Make sure DNS A records point to your **manager node IP**:

- `https://traefik.kronk.uz`
- `https://grafana.kronk.uz`
- `https://prometheus.kronk.uz`
- `https://portainer.kronk.uz`

---

## 🗃️ Project Structure Overview

```plaintext
~/Documents/deployment
├── cluster
│   └── swarm
│       ├── backend
│       │   └── backend_stack.yml
│       ├── monitoring
│       │   ├── alertmanager/
│       │   ├── grafana.yml
│       │   ├── loki/
│       │   ├── prometheus/
│       │   └── promtail.yml
│       └── traefik
│           ├── config/
│           └── traefik.yml
├── pod
│   └── FastAPI source code & Dockerfile
├── service
│   ├── configurations
│   └── docker-compose.yml
└── README.md
```

---

## 🧠 Docker Context Info

```bash
docker context ls
```

Example:

```plaintext
NAME        DESCRIPTION                               DOCKER ENDPOINT               ERROR
default *   Current DOCKER_HOST based configuration   unix:///var/run/docker.sock   
dev-kronk                                             ssh://root@178.212.35.106     
```

Now you’re ready to manage, deploy, and teach Docker Swarm workflows! 🚀
