# REIP nginx setup

Конфиг рассчитан на текущий стенд `reip.grouvi.online`. При переносе на Yandex Cloud замените домен и пути сертификата в `nginx.conf`.

## Первичная установка

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
sudo cp nginx/nginx.conf /etc/nginx/sites-available/reip
sudo ln -s /etc/nginx/sites-available/reip /etc/nginx/sites-enabled/reip
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d reip.grouvi.online
```

Если сертификата ещё нет, сначала создайте временный HTTP-only server block, выполните `certbot`, затем скопируйте полный конфиг и снова запустите `nginx -t`.

## Деплой приложения

```bash
docker compose pull
docker compose up -d --build
curl -fsS http://127.0.0.1:8000/health
sudo nginx -t && sudo systemctl reload nginx
```

## Проверка

```bash
curl -i http://reip.grouvi.online/
curl -fsS https://reip.grouvi.online/health
curl -fsS https://reip.grouvi.online/api/health/deep
```

Первый запрос должен вернуть `301`, второй `{"status":"ok"}`. Перед переносом на YC также перенесите DNS, откройте 80/443 в security group и выпустите новый сертификат уже после переключения A-записи.
