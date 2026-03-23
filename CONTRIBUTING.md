# Contributing to KSeF Monitor

Thank you for your interest in contributing!

*Polska wersja poniżej / Polish version below.*

## Development Setup

```bash
# Clone the repository
git clone https://github.com/mlotocki2k/KSeF_Monitor.git
cd KSeF_Monitor

# Create a virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install test dependencies
pip install pytest pytest-mock

# Copy config template
cp examples/config.example.json config.json
```

## Project Structure

See [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) for a full overview.

## Workflow

1. Create a branch from `test`
2. Make your changes
3. Run tests: `python -m pytest tests/ -v`
4. Test locally (Docker build or standalone)
5. Submit a PR against `test`

## Commit Messages

- Write commit messages in English
- Use descriptive messages explaining *why*, not just *what*
- Add `Co-Authored-By:` trailer when applicable

## Code Conventions

- **Language:** Python 3.11+
- **Logging:** `logger = logging.getLogger(__name__)` — use INFO/WARNING/ERROR levels
- **Error handling:** catch, log, fallback (don't crash)
- **Security:** no secrets in code, use `secrets_manager.py` for credentials

## Tests

Unit tests are in the `tests/` directory. Run them with:

```bash
python -m pytest tests/ -v
```

Tests run automatically on push to `test`/`main` and on PRs (see `.github/workflows/tests.yml`).

## Database Schema Changes

If you modify SQLAlchemy models in `app/database.py`:

```bash
# Generate a new Alembic migration
python -m alembic revision --autogenerate -m "description of change"

# Review the generated migration in alembic/versions/
# Apply the migration
python -m alembic upgrade head
```

Note: SQLite uses `render_as_batch=True` in `alembic/env.py` for ALTER TABLE support.

## Reporting Issues

Use [GitHub Issues](https://github.com/mlotocki2k/KSeF_Monitor/issues) with the provided templates.

---

# Współtworzenie KSeF Monitor

Dziękujemy za zainteresowanie projektem!

## Konfiguracja środowiska

```bash
# Sklonuj repozytorium
git clone https://github.com/mlotocki2k/KSeF_Monitor.git
cd KSeF_Monitor

# Utwórz wirtualne środowisko
python3.11 -m venv venv
source venv/bin/activate

# Zainstaluj zależności
pip install -r requirements.txt

# Zainstaluj zależności testowe
pip install pytest pytest-mock

# Skopiuj szablon konfiguracji
cp examples/config.example.json config.json
```

## Struktura projektu

Pełny opis: [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md).

## Proces pracy

1. Utwórz branch z `test`
2. Wprowadź zmiany
3. Uruchom testy: `python -m pytest tests/ -v`
4. Przetestuj lokalnie (Docker build lub standalone)
5. Wyślij PR do brancha `test`

## Wiadomości commitów

- Commity pisz po angielsku
- Opisuj *dlaczego*, nie tylko *co* się zmieniło
- Dodawaj `Co-Authored-By:` gdy dotyczy

## Konwencje kodu

- **Język:** Python 3.11+
- **Logowanie:** `logger = logging.getLogger(__name__)` — poziomy INFO/WARNING/ERROR
- **Obsługa błędów:** catch, log, fallback (nie crash)
- **Bezpieczeństwo:** żadnych sekretów w kodzie, dane uwierzytelniające przez `secrets_manager.py`

## Testy

Testy jednostkowe znajdują się w katalogu `tests/`. Uruchomienie:

```bash
python -m pytest tests/ -v
```

Testy uruchamiają się automatycznie przy pushu na `test`/`main` oraz przy PR-ach (`.github/workflows/tests.yml`).

## Zmiany schematu bazy danych

Jeśli modyfikujesz modele SQLAlchemy w `app/database.py`:

```bash
# Wygeneruj nową migrację Alembic
python -m alembic revision --autogenerate -m "opis zmiany"

# Przejrzyj wygenerowaną migrację w alembic/versions/
# Zastosuj migrację
python -m alembic upgrade head
```

Uwaga: SQLite używa `render_as_batch=True` w `alembic/env.py` do obsługi ALTER TABLE.

## Zgłaszanie problemów

Użyj [GitHub Issues](https://github.com/mlotocki2k/KSeF_Monitor/issues) — dostępne są szablony zgłoszeń.
