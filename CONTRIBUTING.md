# Contributing to KSeF Monitor

Thank you for your interest in contributing!

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

# Copy config template
cp examples/config.example.json config.json
```

## Project Structure

See [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) for a full overview.

## Workflow

1. Create a branch from `test`
2. Make your changes
3. Test locally (Docker build or standalone)
4. Submit a PR against `test`

## Commit Messages

- Write commit messages in English
- Use descriptive messages explaining *why*, not just *what*
- Add `Co-Authored-By:` trailer when applicable

## Code Conventions

- **Language:** Python 3.11+
- **Logging:** `logger = logging.getLogger(__name__)` — use INFO/WARNING/ERROR levels
- **Error handling:** catch, log, fallback (don't crash)
- **Security:** no secrets in code, use `secrets_manager.py` for credentials

## Reporting Issues

Use [GitHub Issues](https://github.com/mlotocki2k/KSeF_Monitor/issues) with the provided templates.
