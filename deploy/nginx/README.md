# nginx для REIP

`reip.grouvi.online.conf` — единственный конфиг проекта, ровно то, что стоит на
боевой машине в Yandex Cloud. Раньше рядом лежал ещё `nginx/nginx.conf`, который
никогда не устанавливали; он удалён, всё полезное из него перенесено сюда.

## Установка

```bash
sudo cp deploy/nginx/reip.grouvi.online.conf /etc/nginx/conf.d/
sudo nginx -t && sudo systemctl reload nginx
```

## Сертификат

Сертификат Let's Encrypt выпущен на `reip.grouvi.online` и продлевается
системным таймером `certbot.timer`. Проверить:

```bash
sudo certbot certificates
sudo systemctl list-timers certbot.timer
```

Продление ходит по HTTP на `/.well-known/acme-challenge/`, поэтому 80-й порт в
конфиге остаётся открытым и не редиректится целиком на HTTPS.

## Проверка

```bash
curl -sI http://reip.grouvi.online/ | head -1
curl -fsS https://reip.grouvi.online/health
curl -fsS https://reip.grouvi.online/api/health/deep
```

Первый запрос отвечает `301`, второй — `{"status":"ok"}`.
