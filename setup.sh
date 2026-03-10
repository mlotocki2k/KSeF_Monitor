#!/bin/bash
# KSeF Invoice Monitor v0.3 - Setup Script
# This script helps you get started quickly

set -e

echo "=================================================="
echo "  KSeF Invoice Monitor v0.3 - Setup Wizard"
echo "=================================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check Docker
echo "Checking prerequisites..."
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker is not installed${NC}"
    echo "Please install Docker first: https://docs.docker.com/get-docker/"
    exit 1
fi
echo -e "${GREEN}✓ Docker found${NC}"

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null 2>&1; then
    echo -e "${RED}✗ Docker Compose is not installed${NC}"
    echo "Please install Docker Compose first"
    exit 1
fi
echo -e "${GREEN}✓ Docker Compose found${NC}"
echo ""

# ──────────────────────────────────────────────
# Step 1: Choose security method
# ──────────────────────────────────────────────
echo -e "${BLUE}Step 1: Security method${NC}"
echo "Choose how to manage secrets:"
echo "1) Environment Variables (.env file) - Recommended for development"
echo "2) Docker Secrets - Recommended for production"
echo "3) Config file only - NOT RECOMMENDED (for testing only)"
read -p "Enter choice [1-3]: " security_choice

case $security_choice in
    1)
        echo -e "${GREEN}Setting up with Environment Variables${NC}"

        # Create .env if it doesn't exist
        if [ ! -f .env ]; then
            cp examples/.env.example .env
            echo -e "${YELLOW}Created .env file from template${NC}"
        else
            echo -e "${YELLOW}.env file already exists, keeping it${NC}"
        fi

        # Create config without secrets
        if [ ! -f config.json ]; then
            cp examples/config.secure.json config.json
            echo -e "${YELLOW}Created config.json (without secrets)${NC}"
        fi

        # Use env docker-compose
        cp docker-compose.env.yml docker-compose.yml
        echo -e "${YELLOW}Configured docker-compose.yml for environment variables${NC}"

        SETUP_METHOD="env"
        ;;

    2)
        echo -e "${GREEN}Setting up with Docker Secrets${NC}"

        # Check if swarm is initialized
        if ! docker info 2>/dev/null | grep -q "Swarm: active"; then
            echo -e "${YELLOW}Docker Swarm not initialized. Initializing...${NC}"
            docker swarm init 2>/dev/null || echo -e "${YELLOW}Swarm init skipped (may already exist)${NC}"
        fi

        # Create config without secrets
        if [ ! -f config.json ]; then
            cp examples/config.secure.json config.json
            echo -e "${YELLOW}Created config.json (without secrets)${NC}"
        fi

        # Use secrets docker-compose
        cp docker-compose.secrets.yml docker-compose.yml
        echo -e "${YELLOW}Configured docker-compose.yml for Docker secrets${NC}"

        SETUP_METHOD="secrets"
        ;;

    3)
        echo -e "${YELLOW}WARNING: This method is NOT RECOMMENDED for production!${NC}"

        # Create full config with placeholders
        if [ ! -f config.json ]; then
            cp examples/config.example.json config.json
            echo -e "${YELLOW}Created config.json (edit with your credentials)${NC}"
        fi

        SETUP_METHOD="config"
        ;;

    *)
        echo -e "${RED}Invalid choice${NC}"
        exit 1
        ;;
esac
echo ""

# ──────────────────────────────────────────────
# Step 2: KSeF configuration
# ──────────────────────────────────────────────
echo -e "${BLUE}Step 2: KSeF API configuration${NC}"

read -p "KSeF environment (test/demo/prod) [test]: " ksef_env
ksef_env=${ksef_env:-test}

read -p "NIP (10 digits): " ksef_nip

if [ -n "$ksef_nip" ] && command -v python3 &> /dev/null; then
    python3 -c "
import json
with open('config.json', 'r') as f:
    config = json.load(f)
config['ksef']['environment'] = '$ksef_env'
config['ksef']['nip'] = '$ksef_nip'
with open('config.json', 'w') as f:
    json.dump(config, f, indent=2)
print('Config updated with KSeF settings')
"
elif [ -n "$ksef_nip" ]; then
    echo -e "${YELLOW}Python3 not found - please manually edit config.json${NC}"
fi
echo ""

# ──────────────────────────────────────────────
# Step 3: Notification channels
# ──────────────────────────────────────────────
echo -e "${BLUE}Step 3: Notification channels${NC}"
echo "Available channels (comma-separated):"
echo "  pushover  - Mobile push notifications (Pushover app)"
echo "  discord   - Discord webhook notifications"
echo "  slack     - Slack webhook notifications"
echo "  email     - Email via SMTP"
echo "  webhook   - Custom HTTP webhook"
echo ""
read -p "Channels [pushover]: " channels_input
channels_input=${channels_input:-pushover}

# Parse channels into JSON array
IFS=',' read -ra CHANNELS <<< "$channels_input"
channels_json="["
first=true
for ch in "${CHANNELS[@]}"; do
    ch=$(echo "$ch" | xargs)  # trim whitespace
    if [ "$first" = true ]; then
        channels_json+="\"$ch\""
        first=false
    else
        channels_json+=", \"$ch\""
    fi
done
channels_json+="]"

if command -v python3 &> /dev/null; then
    python3 -c "
import json
with open('config.json', 'r') as f:
    config = json.load(f)
config['notifications']['channels'] = json.loads('$channels_json')
with open('config.json', 'w') as f:
    json.dump(config, f, indent=2)
print('Notification channels set to: $channels_input')
"
fi
echo ""

# ──────────────────────────────────────────────
# Step 4: Storage settings
# ──────────────────────────────────────────────
echo -e "${BLUE}Step 4: Invoice file storage${NC}"
echo "Save invoice files locally?"
echo "  XML - source invoice data from KSeF + UPO"
echo "  PDF - generated PDF invoices (with QR code)"
read -p "Save XML files? (y/n) [n]: " save_xml
read -p "Save PDF files? (y/n) [n]: " save_pdf

save_xml_bool="false"
save_pdf_bool="false"
output_dir="/data/invoices"
[ "$save_xml" = "y" ] || [ "$save_xml" = "Y" ] && save_xml_bool="true"
[ "$save_pdf" = "y" ] || [ "$save_pdf" = "Y" ] && save_pdf_bool="true"

if [ "$save_xml_bool" = "true" ] || [ "$save_pdf_bool" = "true" ]; then
    read -p "Output directory [/data/invoices]: " output_dir_input
    output_dir=${output_dir_input:-/data/invoices}
fi

if command -v python3 &> /dev/null; then
    python3 -c "
import json
with open('config.json', 'r') as f:
    config = json.load(f)
config.setdefault('storage', {})
config['storage']['save_xml'] = $save_xml_bool
config['storage']['save_pdf'] = $save_pdf_bool
config['storage']['output_dir'] = '$output_dir'
with open('config.json', 'w') as f:
    json.dump(config, f, indent=2)
print('Storage: save_xml=$save_xml_bool, save_pdf=$save_pdf_bool')
"
fi
echo ""

# ──────────────────────────────────────────────
# Step 5: Monitoring schedule
# ──────────────────────────────────────────────
echo -e "${BLUE}Step 5: Check schedule${NC}"
echo "How often to check for new invoices?"
echo "1) Every N minutes (default: 5)"
echo "2) Every N hours"
echo "3) Daily at specific time"
read -p "Enter choice [1]: " schedule_choice
schedule_choice=${schedule_choice:-1}

case $schedule_choice in
    1)
        read -p "Interval in minutes [5]: " interval
        interval=${interval:-5}
        schedule_mode="minutes"
        ;;
    2)
        read -p "Interval in hours [1]: " interval
        interval=${interval:-1}
        schedule_mode="hourly"
        ;;
    3)
        read -p "Time (HH:MM) [09:00]: " check_time
        check_time=${check_time:-09:00}
        schedule_mode="daily"
        ;;
    *)
        interval=5
        schedule_mode="minutes"
        ;;
esac

if command -v python3 &> /dev/null; then
    python3 -c "
import json
with open('config.json', 'r') as f:
    config = json.load(f)
config['schedule']['mode'] = '$schedule_mode'
if '$schedule_mode' in ('minutes', 'hourly'):
    config['schedule']['interval'] = $interval
    config['schedule'].pop('time', None)
else:
    config['schedule']['time'] = '$check_time'
    config['schedule'].pop('interval', None)
with open('config.json', 'w') as f:
    json.dump(config, f, indent=2)
print('Schedule: $schedule_mode')
"
fi
echo ""

# ──────────────────────────────────────────────
# Step 6: Prometheus metrics
# ──────────────────────────────────────────────
echo -e "${BLUE}Step 6: Prometheus metrics${NC}"
read -p "Enable Prometheus metrics endpoint on :8000/metrics? (y/n) [y]: " enable_prom
enable_prom=${enable_prom:-y}

prom_enabled="true"
[ "$enable_prom" = "n" ] || [ "$enable_prom" = "N" ] && prom_enabled="false"

if command -v python3 &> /dev/null; then
    python3 -c "
import json
with open('config.json', 'r') as f:
    config = json.load(f)
config.setdefault('prometheus', {})
config['prometheus']['enabled'] = $prom_enabled
config['prometheus'].setdefault('port', 8000)
with open('config.json', 'w') as f:
    json.dump(config, f, indent=2)
"
fi
echo ""

# ──────────────────────────────────────────────
# Set file permissions
# ──────────────────────────────────────────────
echo -e "${BLUE}Setting file permissions...${NC}"
chmod 644 config.json
echo -e "${GREEN}✓ config.json: 644${NC}"

if [ -f .env ]; then
    chmod 600 .env
    echo -e "${GREEN}✓ .env: 600 (owner-only)${NC}"
fi

mkdir -p data
echo -e "${GREEN}✓ data/ directory created${NC}"
echo ""

# ──────────────────────────────────────────────
# Final summary
# ──────────────────────────────────────────────
echo -e "${GREEN}=================================================="
echo "  Setup complete!"
echo -e "==================================================${NC}"
echo ""

case $SETUP_METHOD in
    env)
        echo -e "${YELLOW}Next steps:${NC}"
        echo ""
        echo "1. Edit .env with your secrets:"
        echo "   nano .env"
        echo ""
        echo "   Required secrets (depending on enabled channels):"
        echo "   - KSEF_TOKEN          (always required)"
        for ch in "${CHANNELS[@]}"; do
            ch=$(echo "$ch" | xargs)
            case $ch in
                pushover)
                    echo "   - PUSHOVER_USER_KEY   (Pushover)"
                    echo "   - PUSHOVER_API_TOKEN  (Pushover)"
                    ;;
                discord)
                    echo "   - DISCORD_WEBHOOK_URL (Discord)"
                    ;;
                slack)
                    echo "   - SLACK_WEBHOOK_URL   (Slack)"
                    ;;
                email)
                    echo "   - EMAIL_PASSWORD      (Email SMTP)"
                    ;;
                webhook)
                    echo "   - WEBHOOK_TOKEN       (Webhook, optional)"
                    ;;
            esac
        done
        echo ""
        echo "2. Start the monitor:"
        echo "   docker-compose up -d"
        ;;
    secrets)
        echo -e "${YELLOW}Next steps:${NC}"
        echo ""
        echo "1. Create Docker secrets:"
        echo '   echo "your-ksef-token" | docker secret create ksef_token -'
        for ch in "${CHANNELS[@]}"; do
            ch=$(echo "$ch" | xargs)
            case $ch in
                pushover)
                    echo '   echo "your-key" | docker secret create pushover_user_key -'
                    echo '   echo "your-token" | docker secret create pushover_api_token -'
                    ;;
                discord)
                    echo '   echo "https://discord.com/api/webhooks/..." | docker secret create discord_webhook_url -'
                    ;;
                slack)
                    echo '   echo "https://hooks.slack.com/services/..." | docker secret create slack_webhook_url -'
                    ;;
                email)
                    echo '   echo "your-smtp-password" | docker secret create email_password -'
                    ;;
                webhook)
                    echo '   echo "your-auth-token" | docker secret create webhook_token -'
                    ;;
            esac
        done
        echo ""
        echo "2. Deploy:"
        echo "   docker stack deploy -c docker-compose.yml ksef"
        ;;
    config)
        echo -e "${YELLOW}Next steps:${NC}"
        echo ""
        echo "1. Edit config.json with your credentials:"
        echo "   nano config.json"
        echo ""
        echo "2. Set secure permissions:"
        echo "   chmod 600 config.json"
        echo ""
        echo "3. Start the monitor:"
        echo "   docker-compose up -d"
        ;;
esac

echo ""
echo "View logs:"
echo "   docker-compose logs -f"
echo ""
echo -e "${BLUE}Documentation:${NC}"
echo "  docs/QUICKSTART.md      - Quick start guide"
echo "  docs/KSEF_TOKEN.md      - How to create KSeF token"
echo "  docs/NOTIFICATIONS.md   - Notification channels setup"
echo "  docs/PDF_GENERATION.md  - PDF invoice generation"
echo "  docs/SECURITY.md        - Security best practices"
echo "  docs/TESTING.md         - Testing guide"
echo "  README.md               - Full documentation"
echo ""
