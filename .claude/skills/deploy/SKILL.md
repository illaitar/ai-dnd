---
name: deploy
description: Ship the current increment to prod — commit (no Claude co-author), push origin main, then git-reset + restart the systemd service on the VPS and verify it's active. Use after a finished, GREEN increment. Optional args = commit message.
---

# Deploy to prod

Раскатывает текущий зелёный инкремент на боевой сервер. Прод крутится ПРЯМО на VPS (не Docker):
git reset --hard на `main` + рестарт systemd-сервиса. Домашний хост 192.168.3.26 — dev-only, сюда НЕ деплоим.

## Факты окружения (не выдумывать)

- **Прод:** `root@154.222.8.94`, репозиторий `/root/dnd-ai`, systemd-сервис `aidnd`.
- **Публично:** https://kleit.pserver.space (через Caddy).
- **Ветка деплоя:** `main`. Прод делает `git reset --hard origin/main` — только запушенное в main уезжает.
- **live.db** на проде в .gitignore → деплой НЕ трёт прогресс игроков. `worlds.db` (пул) — в гите, едет с коммитом.

## Предусловия

1. **Всё зелёное.** Прогнать `uv run pytest -q` — деплоим только при passed. Если красно — НЕ деплоить.
2. **На ветке `main`** (`git branch --show-current`). Если нет — не деплоить, сказать пользователю.
3. Изменения осмысленно закоммичены.

## Шаги

1. **Коммит** (если есть незакоммиченное и передано сообщение в args):
   - `git add <конкретные файлы>` — не `-A` вслепую; проверить `git status`.
   - `git commit -m "<сообщение>"` — сообщение по-русски, в стиле истории (`feat(область): …` / `docs(область): …`).
   - **КРИТИЧНО: НЕ добавлять трейлер `Co-Authored-By: Claude`** — пользователь вычистил его из истории. Никаких `🤖 Generated with…` тоже.
2. **Push:** `git push -q origin main`
3. **Раскатка на проде** (одной командой):
   ```
   ssh root@154.222.8.94 'cd /root/dnd-ai && git fetch -q && git reset --hard origin/main -q && systemctl restart aidnd && sleep 2 && systemctl is-active aidnd'
   ```
4. **Проверка:** вывод последней команды должен быть `active`. Если нет — сервис не поднялся:
   - Диагностика: `ssh root@154.222.8.94 'journalctl -u aidnd -n 40 --no-pager'`
   - Разобраться и починить, не оставлять прод лежачим.

## После деплоя

- Отметить `✔ на проде` в соответствующем разделе `docs/` (если инкремент по дизайн-канону).
- Обновить память (`live-состояние` мира), если поменялось «что на проде».
- Деплоить **автономно** — не спрашивать разрешения перед commit/push/restart для законченного зелёного инкремента.
