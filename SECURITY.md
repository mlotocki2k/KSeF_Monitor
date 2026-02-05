# Security Guide - Protecting Sensitive Credentials

This guide explains multiple methods to secure your API tokens and credentials for the KSeF Invoice Monitor.

## 🔐 Security Methods Overview

| Method | Security Level | Complexity | Best For |
|--------|---------------|------------|----------|
| Environment Variables | Medium | Low | Development |
| Docker Secrets | High | Medium | Production |
| Config File Only | Low | Very Low | **NOT RECOMMENDED** |
| External Vault | Very High | High | Enterprise |

## Method 1: Environment Variables (Recommended for Development)

### How It Works

Sensitive credentials are stored in a `.env` file and loaded as environment variables. The application reads them instead of storing in `config.json`.

### Setup

1. **Create .env file:**
   ```bash
   cp .env.example .env
   ```

2. **Edit .env with your credentials:**
   ```bash
   KSEF_TOKEN=your-actual-ksef-token-here
   PUSHOVER_USER_KEY=your-pushover-user-key
   PUSHOVER_API_TOKEN=your-pushover-api-token
   ```

3. **Use secure config file:**
   ```bash
   cp config.secure.json config.json
   ```

4. **Use environment-enabled docker-compose:**
   ```bash
   cp docker-compose.env.yml docker-compose.yml
   ```

5. **Run:**
   ```bash
   docker-compose up -d
   ```

### Advantages
✅ Credentials separate from code
✅ `.env` file in `.gitignore` (won't be committed)
✅ Easy to update credentials
✅ No rebuild required

### File Permissions
```bash
chmod 600 .env          # Only owner can read/write
chmod 644 config.json   # Everyone can read, owner can write
```

## Method 2: Docker Secrets (Recommended for Production)

### How It Works

Docker Secrets is a secure way to manage sensitive data in Docker Swarm. Secrets are encrypted and only available to authorized services.

### Setup for Docker Swarm

1. **Initialize Swarm (if not already):**
   ```bash
   docker swarm init
   ```

2. **Create secrets:**
   ```bash
   # KSeF token
   echo "your-ksef-token" | docker secret create ksef_token -
   
   # Pushover credentials
   echo "your-pushover-user-key" | docker secret create pushover_user_key -
   echo "your-pushover-api-token" | docker secret create pushover_api_token -
   ```

3. **Verify secrets created:**
   ```bash
   docker secret ls
   ```

4. **Use secure config:**
   ```bash
   cp config.secure.json config.json
   ```

5. **Deploy with secrets:**
   ```bash
   docker stack deploy -c docker-compose.secrets.yml ksef
   ```

### Setup for Docker Compose (Development Secrets)

For local development without Swarm:

1. **Create secrets directory:**
   ```bash
   mkdir -p secrets
   chmod 700 secrets
   ```

2. **Create secret files:**
   ```bash
   echo "your-ksef-token" > secrets/ksef_token
   echo "your-pushover-user-key" > secrets/pushover_user_key
   echo "your-pushover-api-token" > secrets/pushover_api_token
   
   chmod 600 secrets/*
   ```

3. **Update docker-compose.yml:**
   ```yaml
   secrets:
     ksef_token:
       file: ./secrets/ksef_token
     pushover_user_key:
       file: ./secrets/pushover_user_key
     pushover_api_token:
       file: ./secrets/pushover_api_token
   ```

### Advantages
✅ Encrypted at rest and in transit
✅ Centralized secret management
✅ Automatic rotation support
✅ Access control
✅ Production-grade security

### Managing Secrets

**Update a secret:**
```bash
# Remove old secret
docker secret rm ksef_token

# Create new secret
echo "new-token" | docker secret create ksef_token -

# Redeploy service
docker service update --secret-rm ksef_token --secret-add ksef_token ksef_ksef-monitor
```

**List secrets:**
```bash
docker secret ls
```

**Inspect secret (won't show value):**
```bash
docker secret inspect ksef_token
```

## Method 3: Config File Only (NOT RECOMMENDED)

### Security Risks
❌ Tokens visible in plain text
❌ Easy to accidentally commit to git
❌ Difficult to rotate credentials
❌ No encryption

### When to Use
Only for:
- Quick testing
- Throwaway environments
- Demo purposes

### If You Must Use This Method

1. **Use restrictive file permissions:**
   ```bash
   chmod 600 config.json
   chown root:root config.json
   ```

2. **Verify .gitignore:**
   ```bash
   cat .gitignore | grep config.json
   ```

3. **Encrypt the file system:**
   Use encrypted storage for the directory containing config.json

## Method 4: External Secrets Vault (Enterprise)

For enterprise deployments, integrate with external secret managers:

### HashiCorp Vault

```python
# Example integration (add to secrets_manager.py)
import hvac

client = hvac.Client(url='https://vault.example.com')
secret = client.secrets.kv.v2.read_secret_version(path='ksef/tokens')
token = secret['data']['data']['ksef_token']
```

### AWS Secrets Manager

```python
import boto3

client = boto3.client('secretsmanager')
response = client.get_secret_value(SecretId='ksef/prod/token')
token = response['SecretString']
```

### Azure Key Vault

```python
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential

client = SecretClient(vault_url="https://myvault.vault.azure.net", 
                      credential=DefaultAzureCredential())
token = client.get_secret("ksef-token").value
```

## Priority Order

The application loads secrets in this order (first found wins):

1. **Environment Variables** (highest priority)
2. **Docker Secrets**
3. **Config File** (lowest priority)

This allows you to:
- Use config file for development
- Override with environment variables for testing
- Use Docker secrets for production

## Security Best Practices

### General
✅ Never commit secrets to version control
✅ Use `.gitignore` for sensitive files
✅ Rotate credentials regularly (quarterly minimum)
✅ Use different credentials for test/production
✅ Monitor access logs
✅ Use principle of least privilege

### File Permissions
```bash
# Secrets should be readable only by owner
chmod 600 .env
chmod 600 secrets/*
chmod 600 config.json  # if it contains secrets

# Directories should be protected
chmod 700 secrets/
chmod 700 data/
```

### Docker Security
```bash
# Don't run as root (already handled in Dockerfile)
# Scan for vulnerabilities
docker scan ksef-invoice-monitor

# Use read-only mounts where possible (already configured)
# Enable content trust
export DOCKER_CONTENT_TRUST=1
```

### Network Security
- Use HTTPS for all API calls (enforced)
- Enable firewall rules
- Use private networks for production
- Consider VPN for sensitive operations

## Verification

### Check What Secrets Are Loaded

```bash
# View logs (secrets are masked)
docker-compose logs | grep "loaded from"

# Should see:
# KSeF token loaded from secure source
# Pushover user key loaded from secure source
# Pushover API token loaded from secure source
```

### Test Secret Loading

```bash
docker-compose exec ksef-monitor python3 -c "
from app.config_manager import ConfigManager
config = ConfigManager('/data/config.json')
print('✓ Config loaded successfully')
print('Environment:', config.get('ksef', 'environment'))
print('Secrets loaded:', 'token' in str(config.get('ksef', 'token')))
"
```

## Incident Response

### If Credentials Are Compromised

1. **Immediately revoke the compromised credentials:**
   - KSeF: Revoke token in KSeF portal
   - Pushover: Regenerate API token

2. **Generate new credentials:**
   - Create new tokens
   - Update secrets

3. **Rotate secrets:**
   ```bash
   # Docker secrets
   docker secret rm ksef_token
   echo "new-token" | docker secret create ksef_token -
   docker service update --secret-rm ksef_token --secret-add ksef_token ksef_ksef-monitor
   ```

4. **Review access logs:**
   - Check for unauthorized access
   - Document the incident

5. **Update security measures:**
   - Implement additional controls
   - Review and update this guide

## Compliance Considerations

### GDPR
- Credentials may be considered personal data
- Implement appropriate security measures
- Document data processing

### PCI DSS (if applicable)
- Encrypt credentials at rest and in transit
- Implement access controls
- Maintain audit logs

### SOC 2
- Document security policies
- Implement change management
- Regular security reviews

## Recommended Setup by Environment

### Development
```bash
Method: Environment Variables (.env file)
Config: config.secure.json
Compose: docker-compose.env.yml
Permissions: 600 on .env
```

### Staging
```bash
Method: Docker Secrets (file-based)
Config: config.secure.json
Compose: docker-compose.secrets.yml
Permissions: 700 on secrets/
```

### Production
```bash
Method: Docker Secrets (Swarm) or External Vault
Config: config.secure.json
Deploy: docker stack deploy
Monitoring: Enabled
Audit Logging: Enabled
```

## Quick Start Examples

### Development Setup
```bash
# 1. Setup
cp .env.example .env
cp config.secure.json config.json
cp docker-compose.env.yml docker-compose.yml

# 2. Edit secrets
nano .env

# 3. Set permissions
chmod 600 .env

# 4. Run
docker-compose up -d
```

### Production Setup
```bash
# 1. Setup
cp config.secure.json config.json
cp docker-compose.secrets.yml docker-compose.yml

# 2. Create secrets
echo "prod-token" | docker secret create ksef_token -
echo "prod-user" | docker secret create pushover_user_key -
echo "prod-api" | docker secret create pushover_api_token -

# 3. Deploy
docker stack deploy -c docker-compose.yml ksef
```

## Support

For security questions or to report vulnerabilities:
- Open a GitHub issue (do NOT include actual credentials)
- Contact maintainers directly for sensitive matters

---

**Remember: Security is not a one-time setup, it's an ongoing process.**
