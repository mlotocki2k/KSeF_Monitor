# KSeF Invoice Monitor - Documentation Index

**Version:** 2.0.0  
**Based on:** KSeF API v2.0  
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

### 🔐 Security

| Document | Description | Read When |
|----------|-------------|-----------|
| **[SECURITY.md](SECURITY.md)** | Complete security guide | Before production deployment |
| **[.env.example](.env.example)** | Environment variables template | Setting up secrets |

**Key Security Methods:**
- ✅ Environment Variables (.env) - Development
- ✅ Docker Secrets - Production
- ❌ Config file only - Testing only

### 🏗️ Architecture & Development

| Document | Description | Read When |
|----------|-------------|-----------|
| **[PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)** | Architecture details | Understanding code organization |
| **[IDE_TROUBLESHOOTING.md](IDE_TROUBLESHOOTING.md)** | Fix IDE import errors | Seeing import warnings in IDE |

**For Developers:**
- Modular design with separate files per component
- Hot reload support (no rebuild needed)
- Comprehensive inline documentation

### 🧪 In Development Features

| Document | Description | Status |
|----------|-------------|--------|
| **[PDF_GENERATION.md](PDF_GENERATION.md)** | Generate PDF from KSeF invoices | ⚠️ **IN DEVELOPMENT** |

**PDF Generation:**
- ✅ Fetch invoice XML by KSeF number
- ✅ Parse FA_VAT format
- ✅ Generate PDF according to KSeF template
- ❌ Not yet integrated with main app

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
| **Generate Invoice PDF** | `python test_invoice_pdf.py <ksef-number>` | [PDF_GENERATION.md](PDF_GENERATION.md) |
| **Test Setup** | See [TESTING.md](TESTING.md) | [TESTING.md](TESTING.md) |
| **Fix IDE Errors** | See [IDE_TROUBLESHOOTING.md](IDE_TROUBLESHOOTING.md) | [IDE_TROUBLESHOOTING.md](IDE_TROUBLESHOOTING.md) |
| **Secure Secrets** | See [SECURITY.md](SECURITY.md) | [SECURITY.md](SECURITY.md) |

### File Structure

```
ksef-invoice-monitor/
├── 📄 Documentation
│   ├── README.md                    # Main documentation
│   ├── QUICKSTART.md               # Quick setup guide
│   ├── SECURITY.md                 # Security practices
│   ├── PDF_GENERATION.md           # [IN DEV] PDF generation guide
│   ├── PROJECT_STRUCTURE.md        # Architecture
│   ├── IDE_TROUBLESHOOTING.md      # IDE fixes
│   ├── TESTING.md                  # Test guide
│   └── INDEX.md                    # This file
│
├── 🚀 Application
│   ├── main.py                     # Entry point
│   ├── test_invoice_pdf.py         # [IN DEV] PDF test script
│   └── app/                        # Application package
│       ├── __init__.py
│       ├── secrets_manager.py      # Secrets handling
│       ├── config_manager.py       # Configuration
│       ├── ksef_client.py          # KSeF API client
│       ├── invoice_pdf_generator.py # [IN DEV] PDF generator
│       ├── prometheus_metrics.py   # Prometheus metrics
│       ├── scheduler.py            # Flexible scheduling
│       └── notifiers/              # Multi-channel notifications
│           ├── notification_manager.py
│           ├── pushover_notifier.py
│           ├── discord_notifier.py
│           ├── slack_notifier.py
│           ├── email_notifier.py
│           └── webhook_notifier.py
│
├── ⚙️ Configuration
│   ├── config.example.json         # Config template (with secrets)
│   ├── config.secure.json          # Config template (without secrets)
│   ├── config.json                 # Your config (git-ignored)
│   ├── .env.example                # Environment template
│   └── .env                        # Your secrets (git-ignored)
│
├── 🐳 Docker
│   ├── Dockerfile                  # Image definition
│   ├── docker-compose.yml          # Standard compose
│   ├── docker-compose.env.yml      # With env vars
│   ├── docker-compose.secrets.yml  # With Docker secrets
│   └── requirements.txt            # Python dependencies
│
├── 🔧 Scripts
│   ├── setup.sh                    # Setup wizard
│   └── .gitignore                  # Git exclusions
│
└── 💾 Data (created at runtime)
    └── data/
        └── last_check.json         # Application state
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

**Current Version:** 2.0.0

**Features:**
- ✅ Full KSeF API v2.0 support
- ✅ Multi-channel notifications (5 channels)
- ✅ Prometheus metrics endpoint
- ✅ Flexible scheduling system
- ✅ Token-based authentication
- ✅ Multiple security options
- ✅ Modular architecture
- ✅ Hot reload support
- ✅ Comprehensive documentation
- ✅ Docker deployment
- ✅ Production ready
- 🧪 PDF invoice generation (IN DEVELOPMENT)

**Requirements:**
- Docker & Docker Compose
- At least one notification channel (Pushover, Discord, Slack, Email, or Webhook)
- KSeF authorization token
- Optional: reportlab for PDF generation (IN DEV)

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
