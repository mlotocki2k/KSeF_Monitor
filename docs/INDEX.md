# KSeF Monitor - Documentation Index

**Version:** v0.4
**Based on:** KSeF API v2.2.0
**License:** MIT

---

## 📚 Documentation Guide

This project includes comprehensive documentation. Start here to find what you need:

### 🚀 Getting Started

| Document | Description | Read When |
|----------|-------------|-----------|
| **[QUICKSTART.md](QUICKSTART.md)** | 5-minute setup guide | First time setup |
| **[README.md](README.md)** | Complete documentation | Need full details |
| **[setup.sh](setup.sh)** | Automated setup script | Want easy installation |

**Quick Commands:**
```bash
# Fastest way to get started
chmod +x setup.sh && ./setup.sh
```

### 🔑 KSeF Token & Authentication

| Document | Description | Read When |
|----------|-------------|-----------|
| **[KSEF_TOKEN.md](KSEF_TOKEN.md)** | KSeF token creation (step-by-step) | Setting up KSeF access |

### 🔔 Notifications

| Document | Description | Read When |
|----------|-------------|-----------|
| **[NOTIFICATIONS.md](NOTIFICATIONS.md)** | All 5 notification channels guide | Configuring notifications |
| **[TEMPLATES.md](TEMPLATES.md)** | Jinja2 notification templates (v0.3) | Customizing notification format |

### 🔐 Security

| Document | Description | Read When |
|----------|-------------|-----------|
| **[SECURITY.md](SECURITY.md)** | Complete security guide | Before production deployment |
| **[.env.example](.env.example)** | Environment variables template | Setting up secrets |

**Key Security Methods:**
- ✅ Environment Variables (.env) - Development
- ✅ Docker Secrets - Production
- ❌ Config file only - Testing only

### 🤝 Contributing & Community

| Document | Description | Read When |
|----------|-------------|-----------|
| **[CONTRIBUTING.md](../CONTRIBUTING.md)** | Development setup & workflow | Want to contribute |
| **[CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md)** | Community guidelines | Before contributing |
| **[Issues](https://github.com/mlotocki2k/KSeF_Monitor/issues)** | Report bugs or request features | Found an issue |

### 💾 Database

| Document | Description | Read When |
|----------|-------------|-----------|
| **[DATABASE.md](DATABASE.md)** | DB usage, config, db_admin.py CLI (v0.3) | Managing invoice database |
| **[DATABASE_DESIGN.md](DATABASE_DESIGN.md)** | Full multi-phase schema design | Understanding DB architecture |

### 🏗️ Architecture & Development

| Document | Description | Read When |
|----------|-------------|-----------|
| **[PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)** | Architecture details | Understanding code organization |
| **[KSEF_API_LIMITATIONS.md](KSEF_API_LIMITATIONS.md)** | KSeF API limits & constraints | Understanding API boundaries |
| **[IDE_TROUBLESHOOTING.md](IDE_TROUBLESHOOTING.md)** | Fix IDE import errors | Seeing import warnings in IDE |

**For Developers:**
- Modular design with separate files per component
- Hot reload support (no rebuild needed)
- Comprehensive inline documentation

### 📄 PDF & XML Storage

| Document | Description | Read When |
|----------|-------------|-----------|
| **[PDF_GENERATION.md](PDF_GENERATION.md)** | PDF generation from KSeF invoices | Configuring file storage |
| **[PDF_TEMPLATES.md](PDF_TEMPLATES.md)** | Custom invoice PDF templates (v0.3) | Customizing PDF appearance |

**Features:**
- ✅ Fetch invoice XML by KSeF number
- ✅ Parse FA(3) format (full schema compliance)
- ✅ Generate PDF with QR code, Polish characters
- ✅ Two rendering engines: xhtml2pdf (primary) + ReportLab (fallback)
- ✅ Integrated with main app (config: `storage.save_pdf`)
- ✅ Configurable output directory with folder structure patterns (v0.3)
- ✅ Safe file writing: skip/rename/overwrite strategy (v0.3)
- ✅ Custom HTML/CSS templates for PDF appearance (v0.3)

### 🧪 Testing & Quality

| Document | Description | Read When |
|----------|-------------|-----------|
| **[TESTING.md](TESTING.md)** | Complete testing guide | Before deployment |

**Test Coverage:**
- Configuration validation
- Component tests
- Integration tests
- Security tests
- Performance tests

### 📦 Configuration Files

| File | Purpose | Security Level |
|------|---------|----------------|
| `config.example.json` | Template with all options | Safe to commit |
| `config.secure.json` | Template without secrets | Safe to commit |
| `config.json` | Your actual config | **NEVER COMMIT** |
| `.env.example` | Environment template | Safe to commit |
| `.env` | Your actual secrets | **NEVER COMMIT** |

### 🐳 Docker Configurations

| File | Purpose | Use For |
|------|---------|---------|
| `docker-compose.yml` | Standard setup | Basic usage |
| `docker-compose.env.yml` | Environment variables | Development |
| `docker-compose.secrets.yml` | Docker secrets | Production |
| `Dockerfile` | Image definition | Building |

---

## 📖 Quick Reference

### Common Tasks

| Task | Command | Documentation |
|------|---------|---------------|
| **First Setup** | `./setup.sh` | [QUICKSTART.md](QUICKSTART.md) |
| **Start Monitor** | `docker-compose up -d` | [QUICKSTART.md](QUICKSTART.md) |
| **View Logs** | `docker-compose logs -f` | [README.md](README.md) |
| **Stop Monitor** | `docker-compose down` | [README.md](README.md) |
| **Trigger Check** | `docker kill -s SIGUSR1 ksef-monitor` | [README.md](README.md) |
| **Generate Invoice PDF** | `python examples/test_invoice_pdf.py <ksef-number>` | [PDF_GENERATION.md](PDF_GENERATION.md) |
| **Test Setup** | See [TESTING.md](TESTING.md) | [TESTING.md](TESTING.md) |
| **Fix IDE Errors** | See [IDE_TROUBLESHOOTING.md](IDE_TROUBLESHOOTING.md) | [IDE_TROUBLESHOOTING.md](IDE_TROUBLESHOOTING.md) |
| **Secure Secrets** | See [SECURITY.md](SECURITY.md) | [SECURITY.md](SECURITY.md) |
| **DB Status** | `python db_admin.py status` | [DATABASE.md](DATABASE.md) |
| **List Invoices** | `python db_admin.py invoices` | [DATABASE.md](DATABASE.md) |
| **DB Statistics** | `python db_admin.py stats` | [DATABASE.md](DATABASE.md) |
| **Export Invoices** | `python db_admin.py export-invoices -o file.csv` | [DATABASE.md](DATABASE.md) |

### File Structure

```
KSeF_Monitor/
├── 📄 Documentation
│   ├── README.md                    # Main documentation
│   ├── docs/QUICKSTART.md          # Quick setup guide
│   ├── docs/KSEF_TOKEN.md          # KSeF token creation guide
│   ├── docs/NOTIFICATIONS.md       # Notification channels guide
│   ├── docs/TEMPLATES.md           # Jinja2 templates guide
│   ├── docs/SECURITY.md            # Security practices
│   ├── docs/PDF_GENERATION.md      # PDF generation guide
│   ├── docs/PDF_TEMPLATES.md       # Custom PDF templates guide
│   ├── docs/PROJECT_STRUCTURE.md   # Architecture
│   ├── docs/ROADMAP.md             # Project roadmap
│   ├── docs/TESTING.md             # Test guide
│   ├── docs/IDE_TROUBLESHOOTING.md # IDE fixes
│   └── docs/INDEX.md               # This file
│
├── 🚀 Application
│   ├── main.py                     # Entry point
│   └── app/                        # Application package
│       ├── config_manager.py       # Configuration
│       ├── secrets_manager.py      # Secrets handling
│       ├── ksef_client.py          # KSeF API v2.1 client (rate limited)
│       ├── invoice_monitor.py      # Main monitoring logic
│       ├── rate_limiter.py         # Sliding window rate limiter (v0.4)
│       ├── database.py             # SQLite + SQLAlchemy 2.0 ORM
│       ├── invoice_xml_parser.py   # FA(3) XML parser (v0.4)
│       ├── pdf_constants.py        # PDF constants (v0.4)
│       ├── invoice_pdf_generator.py # ReportLab PDF (fallback)
│       ├── invoice_pdf_template.py  # HTML/CSS → PDF via xhtml2pdf (primary)
│       ├── template_renderer.py    # Jinja2 template engine
│       ├── prometheus_metrics.py   # Prometheus metrics (9 metrics)
│       ├── scheduler.py            # Flexible scheduling (5 modes)
│       ├── logging_config.py       # Logging with timezone
│       ├── templates/              # Built-in Jinja2 templates (6 files)
│       ├── api/                    # REST API (FastAPI, v0.4)
│       │   ├── __init__.py         # App factory + auth + security headers
│       │   ├── server.py           # Uvicorn daemon thread
│       │   ├── schemas.py          # Pydantic response models
│       │   └── routers/            # API endpoints (invoices, stats, monitor, artifacts)
│       └── notifiers/              # Multi-channel notifications (5 channels)
│
├── ⚙️ Configuration & Examples
│   ├── examples/config.example.json # Config template (with secrets)
│   ├── examples/config.secure.json  # Config template (without secrets)
│   ├── examples/.env.example        # Environment template
│   ├── examples/test_invoice_pdf.py # CLI test script for PDF
│   ├── config.json                  # Your config (git-ignored)
│   └── .env                         # Your secrets (git-ignored)
│
├── 📋 Specs
│   ├── spec/openapi.json           # KSeF API v2.2.0 OpenAPI spec (production)
│   ├── spec/openapi-test.json      # KSeF API OpenAPI spec (test)
│   ├── spec/openapi-demo.json      # KSeF API OpenAPI spec (demo)
│   └── spec/schemat_FA(3)_v1-0E.xsd # FA(3) invoice XSD schema
│
├── 🐳 Docker
│   ├── Dockerfile                  # Image definition (OCI labels, healthcheck)
│   ├── entrypoint.sh               # Docker entrypoint (gosu, ownership fix)
│   ├── docker-compose.yml          # Standard compose
│   ├── docker-compose.env.yml      # With env vars
│   ├── docker-compose.secrets.yml  # With Docker secrets
│   └── requirements.txt            # Python dependencies
│
├── 🤝 Community & CI
│   ├── CONTRIBUTING.md             # How to contribute
│   ├── CODE_OF_CONDUCT.md          # Community guidelines
│   ├── pyproject.toml              # Python project metadata
│   └── .github/
│       ├── ISSUE_TEMPLATE/         # Issue templates (bug, feature)
│       ├── PULL_REQUEST_TEMPLATE.md # PR template
│       └── workflows/              # GitHub Actions (5 workflows)
│
├── 🔧 Scripts & Tools
│   ├── setup.sh                    # Setup wizard
│   ├── db_admin.py                 # Database administration CLI
│   └── .gitignore                  # Git exclusions
│
├── 💾 Database Migrations
│   ├── alembic.ini                 # Alembic configuration
│   └── alembic/                    # Migration scripts
│
└── 💾 Data (created at runtime)
    └── data/
        ├── invoices.db             # SQLite database (v0.3)
        └── last_check.json         # Legacy state (auto-migrated to DB)
```

---

## 🎯 Choose Your Path

### Path 1: Quick Start (5 minutes)
1. Read [QUICKSTART.md](QUICKSTART.md)
2. Run `./setup.sh`
3. Start monitoring!

### Path 2: Secure Production Setup (15 minutes)
1. Read [QUICKSTART.md](QUICKSTART.md)
2. Read [SECURITY.md](SECURITY.md)
3. Use Docker Secrets method
4. Run tests from [TESTING.md](TESTING.md)
5. Deploy!

### Path 3: Developer Setup (30 minutes)
1. Read [README.md](README.md)
2. Read [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)
3. Set up with environment variables
4. Review code in `app/` directory
5. Make customizations!

### Path 4: Understanding Everything (1 hour)
1. Read all documentation in order
2. Review code structure
3. Run all tests
4. Customize as needed

---

## 🆘 Troubleshooting Index

| Problem | Solution | Document |
|---------|----------|----------|
| Import errors in IDE | Not a real problem! | [IDE_TROUBLESHOOTING.md](IDE_TROUBLESHOOTING.md) |
| No notifications | Check Pushover setup | [TESTING.md](TESTING.md) Test 7 |
| Auth failed | Check token & NIP | [TESTING.md](TESTING.md) Test 8 |
| Container won't start | Check config & logs | [QUICKSTART.md](QUICKSTART.md) |
| Security concerns | Read security guide | [SECURITY.md](SECURITY.md) |
| Want to customize | Review structure | [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) |

---

## 📞 Support & Resources

### Documentation
- All docs included in this project
- Inline code documentation in each module
- Examples in TESTING.md

### External Resources
- KSeF API Documentation: [github.com/CIRFMF/ksef-docs](https://github.com/CIRFMF/ksef-docs)
- Pushover API: [pushover.net/api](https://pushover.net/api)
- Docker Documentation: [docs.docker.com](https://docs.docker.com)

### Getting Help
1. Check the relevant documentation above
2. Run tests from [TESTING.md](TESTING.md)
3. Review logs: `docker-compose logs -f`
4. Check configuration files

---

## ✅ Pre-Flight Checklist

Before running in production:

- [ ] Read [QUICKSTART.md](QUICKSTART.md)
- [ ] Read [SECURITY.md](SECURITY.md)
- [ ] Set up Docker Secrets (not .env)
- [ ] Use `config.secure.json` as base
- [ ] Run tests from [TESTING.md](TESTING.md)
- [ ] Set proper file permissions (600)
- [ ] Enable log rotation
- [ ] Test notification delivery
- [ ] Verify KSeF authentication
- [ ] Set appropriate check_interval
- [ ] Document your setup

---

## 📊 Version Information

**Current Version:** v0.4

**Features:**
- ✅ Full KSeF API v2.1 support
- ✅ Multi-channel notifications (5 channels)
- ✅ Customizable Jinja2 notification templates
- ✅ Polish monetary formatting
- ✅ Prometheus metrics endpoint (9 metrics)
- ✅ Flexible scheduling system
- ✅ Token-based authentication
- ✅ Multiple security options
- ✅ Modular architecture
- ✅ Hot reload support
- ✅ Comprehensive documentation
- ✅ Docker deployment
- ✅ Production ready
- ✅ PDF invoice generation (with QR code, Polish characters)
- ✅ Configurable XML/PDF file storage with folder structure patterns
- ✅ SQLite database for invoice metadata + notification log
- ✅ Database admin CLI tool: `db_admin.py`
- ✅ Custom HTML/CSS invoice PDF templates
- ✅ REST API with FastAPI (read-only, Bearer auth, Swagger UI, rate limiting) (v0.4)
- ✅ Sliding window rate limiter (3 windows) (v0.4)
- ✅ API request logging + artifact download tracking (v0.4)
- ✅ Security audit: 10 controls (SSTI sandbox, auth enforcement, rate limiting, CORS, CRLF, info disclosure) (v0.4)
- ✅ 416 unit tests (v0.4)

**Requirements:**
- Docker & Docker Compose
- At least one notification channel (Pushover, Discord, Slack, Email, or Webhook)
- KSeF authorization token

---

## 🎓 Learning Path

**Beginner:**
1. [QUICKSTART.md](QUICKSTART.md) - Get it running
2. [README.md](README.md) - Understand basics
3. [TESTING.md](TESTING.md) - Verify it works

**Intermediate:**
4. [SECURITY.md](SECURITY.md) - Secure your setup
5. [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) - Understand architecture
6. Customize configuration

**Advanced:**
7. Review source code in `app/`
8. Add custom features
9. Integrate with other systems
10. Contribute improvements

---

**Ready to start? Go to [QUICKSTART.md](QUICKSTART.md)!**

*For the complete experience, read [README.md](README.md) first.*
