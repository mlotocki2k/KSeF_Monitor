# IDE Import Resolution Issues - Troubleshooting Guide

If your IDE (VS Code, PyCharm, etc.) shows import errors for `.secrets_manager` or other app modules, this is usually a **linting/IDE issue**, not a runtime problem. The code will run fine in Docker.

## Why This Happens

IDEs sometimes struggle with relative imports in Python packages, especially when:
- The project root is not properly configured
- Python path is not set correctly
- Virtual environment is not activated
- IDE cache is stale

## Solutions

### Option 1: VS Code - Add Python Path (Recommended)

Create `.vscode/settings.json` in your project root:

```json
{
    "python.analysis.extraPaths": [
        "${workspaceFolder}"
    ],
    "python.languageServer": "Pylance",
    "python.analysis.diagnosticMode": "workspace"
}
```

### Option 2: PyCharm - Mark Directory as Source

1. Right-click the project root folder
2. Select "Mark Directory as" → "Sources Root"
3. Invalidate caches: File → Invalidate Caches → Restart

### Option 3: Create Local Virtual Environment

```bash
# Create venv
python3 -m venv venv

# Activate
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Select interpreter in IDE
# VS Code: Ctrl+Shift+P → "Python: Select Interpreter"
# PyCharm: Settings → Project → Python Interpreter
```

### Option 4: Add __pycache__ to .gitignore

The imports work at runtime. If you just want to suppress IDE warnings:

**For VS Code:**
Add to `settings.json`:
```json
{
    "python.analysis.diagnosticSeverityOverrides": {
        "reportMissingImports": "none"
    }
}
```

**For PyCharm:**
1. Settings → Editor → Inspections
2. Uncheck "Unresolved references"

### Option 5: Verify File Structure

Ensure your project structure is correct:

```
KSeF_Monitor/
├── main.py
├── app/
│   ├── __init__.py          ← Must exist!
│   ├── secrets_manager.py
│   ├── config_manager.py
│   ├── ksef_client.py
│   ├── invoice_monitor.py
│   ├── invoice_pdf_generator.py
│   ├── invoice_pdf_template.py
│   ├── template_renderer.py
│   ├── scheduler.py
│   ├── prometheus_metrics.py
│   ├── logging_config.py
│   ├── templates/             ← Built-in Jinja2 templates
│   └── notifiers/
│       ├── __init__.py        ← Must exist!
│       ├── base_notifier.py
│       ├── notification_manager.py
│       ├── pushover_notifier.py
│       ├── discord_notifier.py
│       ├── slack_notifier.py
│       ├── email_notifier.py
│       └── webhook_notifier.py
└── ...
```

Run this to verify:
```bash
ls -la app/
# Should show all .py files including __init__.py
```

## Testing Imports Work

Even if your IDE shows errors, test that imports actually work:

```bash
# Test 1: Import in Python directly
python3 -c "from app.secrets_manager import SecretsManager; print('✓ Import works')"

# Test 2: Run the application
python3 main.py
# Should load without import errors

# Test 3: Test in Docker (most reliable)
docker-compose build
docker-compose up -d
docker-compose logs
# Should show no import errors
```

## Common IDE Error Messages

### "Import could not be resolved"
- **Cause:** IDE can't find module in Python path
- **Fix:** Option 1 or 2 above
- **Impact:** None - code runs fine

### "No module named 'app.secrets_manager'"
- **Cause:** Running from wrong directory
- **Fix:** Run from project root where `main.py` is
- **Check:** `pwd` should show project root

### "Circular import detected"
- **Cause:** IDE incorrectly detects circular import
- **Fix:** Reload window or Option 3
- **Impact:** None - no actual circular import exists

## Project Structure Best Practices

### ✅ Correct Import Style (In Files)

**In `main.py`:**
```python
from app.config_manager import ConfigManager
from app.ksef_client import KSeFClient
```

**In `app/config_manager.py`:**
```python
from .secrets_manager import SecretsManager  # Relative import
```

**In `app/__init__.py`:**
```python
from .secrets_manager import SecretsManager
from .config_manager import ConfigManager
# etc.
```

### ❌ Incorrect Import Styles

**Don't do this in `main.py`:**
```python
from secrets_manager import SecretsManager  # Wrong - not in path
import app.secrets_manager.SecretsManager   # Wrong - not a submodule
```

**Don't do this in `app/config_manager.py`:**
```python
from app.secrets_manager import SecretsManager  # Avoid absolute in package
import secrets_manager  # Won't work
```

## Verifying Runtime Execution

The **only** test that matters is whether the code actually runs:

```bash
# Build and run
docker-compose up -d

# Check logs for import errors
docker-compose logs ksef-monitor | grep -i "import\|error"

# Should see successful startup:
# ✓ Configuration loaded
# ✓ KSeF client initialized
# ✓ Pushover notifier initialized
```

If you see this, **your code is working correctly** regardless of IDE warnings!

## IDE-Specific Configurations

### VS Code Complete Setup

Create `.vscode/settings.json`:
```json
{
    "python.defaultInterpreterPath": "${workspaceFolder}/venv/bin/python",
    "python.analysis.extraPaths": ["${workspaceFolder}"],
    "python.analysis.diagnosticMode": "workspace",
    "python.linting.enabled": true,
    "python.linting.pylintEnabled": true,
    "files.exclude": {
        "**/__pycache__": true,
        "**/*.pyc": true
    }
}
```

### PyCharm Complete Setup

1. **Set project interpreter:**
   - File → Settings → Project → Python Interpreter
   - Add local interpreter → Virtualenv Environment

2. **Mark directories:**
   - Right-click project root → Mark as Sources Root

3. **Configure inspection:**
   - Settings → Editor → Inspections → Python
   - Ensure "Unresolved references" is enabled but not too strict

## Still Having Issues?

### Quick Fix: Ignore IDE Warnings

The code works fine at runtime. To proceed:

1. **Ignore the red squiggles in your IDE**
2. **Run the code in Docker** (recommended way)
3. **Test with:** `docker-compose up -d && docker-compose logs -f`

### Nuclear Option: Recreate __init__.py

If nothing works, try recreating the `__init__.py`:

```bash
cd app/
rm __init__.py

cat > __init__.py << 'EOF'
from .secrets_manager import SecretsManager
from .config_manager import ConfigManager
from .ksef_client import KSeFClient
from .notifiers import NotificationManager
from .invoice_monitor import InvoiceMonitor

__all__ = [
    'SecretsManager',
    'ConfigManager',
    'KSeFClient',
    'NotificationManager',
    'InvoiceMonitor'
]
EOF
```

But honestly, the original one is correct!

## Remember

🎯 **Key Point:** IDE import warnings are cosmetic. If the Docker container runs successfully, your code is correct!

The imports are designed to work in the Docker environment, which is where the application is meant to run.

## Support

If you continue having issues **at runtime** (not just IDE):
1. Share the error message from `docker-compose logs`
2. Verify file structure with `ls -R`
3. Check Python version with `python3 --version`

For IDE-only issues: These don't affect the application and can be safely ignored.
