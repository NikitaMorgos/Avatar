# Документация — task-001-vpn-proxy

## Ссылки

- [Timeweb Cloud — серверы в Германии](https://timeweb.cloud/services/servers-germany)
- [aiogram 3 — Proxy / AiohttpSession](https://docs.aiogram.dev/en/v3.19.0/api/session/aiohttp.html)
- [aiohttp-socks на PyPI](https://pypi.org/project/aiohttp-socks/)

## Timeweb VPS — рекомендованная конфигурация

| Параметр | Значение |
|---|---|
| Локация | Германия (Франкфурт) |
| ОС | Ubuntu 22.04 LTS |
| CPU | 1 vCPU |
| RAM | 1 GB |
| Диск | 15 GB NVMe |
| Цена | ~660 руб/мес |
| Дата-центр | NTT, Tier III |

## SSH SOCKS5-туннель — справка

```powershell
# Разовый запуск туннеля (пока открыт терминал)
ssh -D 1080 -N root@VPS_IP

# Запуск в фоне (одна сессия)
ssh -D 1080 -N -f root@VPS_IP

# С keepalive и автовосстановлением (через скрипт)
ssh -D 1080 -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 root@VPS_IP
```

После запуска: `PROXY=socks5://127.0.0.1:1080` в `.env`.

## Форматы PROXY для .env

```env
# HTTP-прокси
PROXY=http://127.0.0.1:1080

# SOCKS5 (рекомендован для SSH-туннеля)
PROXY=socks5://127.0.0.1:1080

# SOCKS5 с авторизацией
PROXY=socks5://user:pass@host:port
```
