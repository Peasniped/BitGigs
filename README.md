# BitGigs

BitGigs is an open-source Django web application for tracking work hours, estimating net pay, and managing shifts . built with Danish payroll rules in mind.

## Features

- **Multi-workplace support** . manage multiple jobs, each with its own employment type (hourly or salaried), payroll period, and appearance (custom icons and accent colours).
- **Shift tracking** . log work sessions as on-site, remote, sick leave, paid absence, or vacation, with start/end times and configurable break minutes.
- **Planned shifts** . draft and approve upcoming shifts before committing them as actual work sessions.
- **Danish tax calculations** . date-versioned tax profiles covering trÃ¦kprocent, personfradrag, AM-bidrag, and kirkeskat ensure past payslips are never retroactively recalculated.
- **ATP contributions** . bracket-based ATP (Arbejdsmarkedets TillÃ¦gspension) employee/employer contribution calculations.
- **Payroll periods & payslip editor** . generates a full payslip with auto-calculated standard lines plus user-defined pre-tax and post-tax additions/deductions with drag-and-drop reordering.
- **Feriekonto, Fritvalgskonto & Pension** . dedicated tracking per workplace.
- **Calendar view** . visual month calendar showing shifts across all workplaces.
- **Commuting tracking** . counts on-site days per workplace per month for tax/transport purposes.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 6.0 |
| Frontend | Bootstrap 5 (via django-crispy-forms) |
| Database (dev) | SQLite |
| Database (prod) | PostgreSQL |
| Python | 3.11+ |

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/Peasniped/BitGigs.git
cd BitGigs
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Apply migrations and run the development server

The default local settings use SQLite . no database setup required.

```bash
python manage.py migrate --settings=bitgigs.settings.local
python manage.py createsuperuser --settings=bitgigs.settings.local
python manage.py runserver --settings=bitgigs.settings.local
```

Visit `http://127.0.0.1:8000/` in your browser.

### Developing against PostgreSQL (optional)

Dev defaults to SQLite. To use a local PostgreSQL instead, start the bundled
container and flip the dev database switch:

```bash
cp .env.example .env       # set POSTGRES_PASSWORD, uncomment DJANGO_DB=postgres
docker compose up db
python manage.py migrate --settings=bitgigs.settings.local
```

## Running with Docker

The repo ships a production-shaped stack — the app image (gunicorn + WhiteNoise,
hardened production settings) plus PostgreSQL. The app service uses the
pre-built image `ghcr.io/peasniped/bitgigs:latest`, so running it never
requires building the repo:

```bash
cp .env.example .env       # set DJANGO_SECRET_KEY and POSTGRES_PASSWORD
docker compose up
```

While the GHCR package is private, pulling needs a one-time
`docker login ghcr.io` with a read-only PAT (`read:packages`).

### Releasing the image (maintainers)

There is no CI — a release is built and pushed by hand. A locally built tag
also satisfies `docker compose up` without touching the registry, which is how
you test unpushed changes:

```bash
docker build -t ghcr.io/peasniped/bitgigs:latest .
docker push ghcr.io/peasniped/bitgigs:latest    # requires docker login ghcr.io
```

Visit `http://localhost:8000/`. First-run setup asks for the setup key, which is
printed to the app log: `docker compose logs app`. HTTPS enforcement defaults to
off in compose for local use; set `DJANGO_ENABLE_HTTPS=1` in `.env` when serving
behind a TLS-terminating reverse proxy. Media uploads and the setup key live in
the `instance` volume, the database in `pgdata`.

## Settings

The project ships with three settings modules under `bitgigs/settings/`:

| Module | Purpose |
|---|---|
| `base.py` | Shared settings for all environments |
| `local.py` | Development . SQLite, `DEBUG=True` |
| `production.py` | Production . PostgreSQL, `DEBUG=False` |

### Production environment variables

| Variable | Default | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | *(insecure placeholder)* | Django secret key . **must** be set in production |
| `DJANGO_ALLOWED_HOSTS` | *(empty)* | Comma-separated list of allowed hostnames |
| `POSTGRES_DB` | `bitgigs` | PostgreSQL database name |
| `POSTGRES_USER` | `bitgigs` | PostgreSQL username |
| `POSTGRES_PASSWORD` | *(empty)* | PostgreSQL password |
| `POSTGRES_HOST` | `localhost` | PostgreSQL host |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |

## Project Structure

```
bitgigs/          # Project settings and root URL config
core/             # Tax profiles, ATP configuration, and main dashboard
workplaces/       # Workplace models, per-workplace settings and views
shifts/              # Approved and planned shifts
payroll/          # Payroll periods, payslip lines and payslip editor
calendar_view/    # Month calendar view across all workplaces
templates/        # Base HTML templates
static/           # CSS and JavaScript assets
```

## Running Tests

```bash
python manage.py test --settings=bitgigs.settings.local
```

## License

This project is licensed under the terms of the [LICENSE](LICENSE) file.


