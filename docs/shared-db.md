# Shared PostgreSQL Container

Этот проект поднимает PostgreSQL + `pgvector` в контейнере `wb-pgvector`.

Запуск:

```bash
docker compose up -d pgvector
docker compose ps
```

Подключение с хоста:

```text
Host: localhost
Port: 55433
Database: wb_docs
User: wb_user
Password: wb_pass
```

DSN:

```text
postgresql://wb_user:wb_pass@localhost:55433/wb_docs
```

Подключение из другого Docker-проекта:

1. База из этого репозитория должна быть запущена.
2. Другой проект нужно подключить к сети `wb-shared-network`.
3. В другом проекте использовать хост `wb-shared-db` и порт `5432`.

Пример `docker-compose.yml` для другого проекта:

```yaml
services:
  app:
    build: .
    environment:
      DB_HOST: wb-shared-db
      DB_PORT: 5432
      DB_NAME: wb_docs
      DB_USER: wb_user
      DB_PASSWORD: wb_pass
    networks:
      - wb-shared-network

networks:
  wb-shared-network:
    external: true
```

Если другой проект запускается не в Docker, используй `localhost:55433`.
