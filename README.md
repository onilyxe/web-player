# Web - player

Веб-плеєр аудіо з відображенням synced lyrics з тегів файлу. Працює через drag-n-drop у браузері або з локальною бібліотекою на сервері через пароль.


## Можливості

**Публічна частина** (без авторизації):
- Drag-n-drop FLAC, MP3, M4A, MP4, OGG, Opus у браузер → програється + показує текст з тегів
- Адаптивний колір тексту відповідно до обкладинки (як в Apple Music)
- Synced LRC з підсвічуванням активного рядка
- Plain text
- PWA-режим

**Адмін-частина** (за паролем):
- Список треків з вашої локальної бібліотеки
- Пошук за назвою файлу
- Програвання через streaming з підтримкою Range
- Перемикання треків
- Інтеграція з iOS Control Center і Lock Screen — обкладинка, метадані, кнопки керування

**Підтримувані поля з тегами:**

| Формат | Текст | Обкладинка |
|--------|-------|------------|
| FLAC   | `LYRICS`, `UNSYNCEDLYRICS`, `COMMENT` | Picture block |
| MP3    | `USLT`, `COMM`, `TXXX:lyrics` | `APIC` |
| M4A/MP4| `©lyr`, `©cmt` | `covr` |
| OGG    | `lyrics`, `comment` | — |

LRC-таймкоди визначаються автоматично за наявністю патерну `[mm:ss.ms]`. Підтримується `[offset:N]` тег для зсуву.


## Стек

- **Backend:** Python 3.12, FastAPI, Uvicorn, PyJWT, aiofiles
- **Frontend:** vanilla JS (без бандлерів), CSS Variables, Variable Fonts, Canvas API
- **Контейнеризація:** Docker


## Деплой (мій робочий флоу)

Я тримаю проєкт на VPS і керую стеком через Portainer. Образ збираю локально через CLI, Portainer його використовує без re-pull


### 1. Клонування

```bash
git clone https://github.com/onilyxe/web-player.git
cd web-player
```


### 2. Налаштування `docker-compose.yml`

```yaml
- `volumes` → Шлях до вашої бібліотеки музики (`/your/music/directory`)
- `ADMIN_PASSWORD` → Пароль (Згенерувати: `openssl rand -base64 24`)
- `JWT_SECRET` → Секрет для підпису токенів (Згенерувати: `openssl rand -hex 32`)
- `TOKEN_HOURS` → Час життя сесії в годинах (За замовчуванням 24)
```


### 3. Збірка образу локально

```bash
docker build -t web-player:latest . && docker image prune -f
```


### 4. Створення стеку в Portainer

Stacks → Add stack → Web editor → вставити вміст `docker-compose.yml`. Або, якщо файл вже на сервері, можна обрати Repository і вказати локальний шлях.

**Важливо:** не ставити галочку "Re-pull image" при Update — образ локальний, Portainer спробує його шукати в Docker Hub і впаде з 404.


### 5. Реверс-проксі

Я використовую Nginx Proxy Manager у спільній Docker-мережі `proxy`. Налаштування проксі — стандартне (forward на `web-player:80`).


### Оновлення після змін у коді

```bash
cd web-player
git pull
docker build -t web-player:latest . && docker image prune -f
```

Далі в Portainer → стек → Recreate **без галочки Re-pull image**.


## TODO

- [ ] Синхронізація тексту з музикою
- [ ] Зовнішній вигляд тексту на деяких обкладинках
- [ ] Чорна смуга в PWA на iOS
- [ ] Підвищити перформанс
- [ ] Кнопки керування "залипають" в hover-стані після натиску на мобільних