# BitGigs

BitGigs is an open-source Django web application for tracking work hours, estimating net pay, and managing shifts — built with Danish payroll rules in mind.

## Features

- **Multi-workplace support** — manage multiple jobs, each with its own employment type (hourly or salaried), payroll period, and appearance (custom icons and accent colours).
- **Shift tracking** — log work sessions as on-site, remote, sick leave, paid absence, or vacation, with start/end times and configurable break minutes.
- **Planned shifts** — draft and approve upcoming shifts before committing them as actual work sessions.
- **Danish tax calculations** — date-versioned tax profiles covering trækprocent, personfradrag, AM-bidrag, and kirkeskat ensure past payslips are never retroactively recalculated.
- **ATP contributions** — bracket-based ATP (Arbejdsmarkedets Tillægspension) employee/employer contribution calculations.
- **Payroll periods & payslip editor** — generates a full payslip with auto-calculated standard lines plus user-defined pre-tax and post-tax additions/deductions with drag-and-drop reordering.
- **Feriekonto, Fritvalgskonto & Pension** — dedicated tracking per workplace.
- **Calendar view** — visual month calendar showing shifts across all workplaces.
- **Commuting tracking** — counts on-site days per workplace per month for tax/transport purposes.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 5.1 |
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

The default local settings use SQLite — no database setup required.

```bash
python manage.py migrate --settings=bitgigs.settings.local
python manage.py createsuperuser --settings=bitgigs.settings.local
python manage.py runserver --settings=bitgigs.settings.local
```

Visit `http://127.0.0.1:8000/` in your browser.

## Settings

The project ships with three settings modules under `bitgigs/settings/`:

| Module | Purpose |
|---|---|
| `base.py` | Shared settings for all environments |
| `local.py` | Development — SQLite, `DEBUG=True` |
| `production.py` | Production — PostgreSQL, `DEBUG=False` |

### Production environment variables

| Variable | Default | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | *(insecure placeholder)* | Django secret key — **must** be set in production |
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
worksessions/     # Work sessions (shifts) and planned shifts
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

