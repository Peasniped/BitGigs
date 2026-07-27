# Bare-metal deployment (systemd)

BitGigs runs as **two** long-lived processes:

| Process | What it does |
|---|---|
| `bitgigs-web` | The gunicorn web server. |
| `bitgigs-scheduler` | The task-scheduler loop (`manage.py run_scheduler`). |

The scheduler is a **separate process on purpose** — the web server has several
gunicorn workers, and an in-process timer would fire in every one of them. A
single scheduler process runs each job exactly once.

## Install

```sh
sudo cp deploy/systemd/bitgigs-web.service /etc/systemd/system/
sudo cp deploy/systemd/bitgigs-scheduler.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bitgigs-web bitgigs-scheduler
```

Edit `User`, `WorkingDirectory`, the `.venv` path and `EnvironmentFile` in each
unit to match your install first.

## Notes

- **Docker** doesn't use these units — `compose.yaml` runs the app and the
  scheduler as two services from the same image.
- **Dev** doesn't need them either — `python scripts/dev.py` starts runserver
  and the scheduler together in one console.
- Jobs, their cadences and their enabled state live in the database
  (`scheduler.ScheduledJob`, editable in the Django admin); see
  `apps/scheduler/registry.py` for what ships.
- The scheduler is optional: opportunistic housekeeping still runs on ordinary
  requests without it. Run it when a job must fire with no user present.
