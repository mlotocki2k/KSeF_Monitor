#!/bin/bash
# KSeF Invoice Monitor - Setup Script
# This script helps you get started quickly

set -e

echo "=================================================="
echo "  KSeF Invoice Monitor - Setup Wizard"
echo "=================================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check Docker
echo "Checking prerequisites..."
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker is not installed${NC}"
    echo "Please install Docker first: https://docs.docker.com/get-docker/"
    exit 1
fi
echo -e "${GREEN}✓ Docker found${NC}"

if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}✗ Docker Compose is not installed${NC}"
    echo "Please install Docker Compose first"
    exit 1
fi
echo -e "${GREEN}✓ Docker Compose found${NC}"
echo ""

# Choose security method
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
            cp .env.example .env
            echo -e "${YELLOW}Created .env file${NC}"
        else
            echo -e "${YELLOW}.env file already exists${NC}"
        fi
        
        # Create config without secrets
        if [ ! -f config.json ]; then
            cp config.secure.json config.json
            echo -e "${YELLOW}Created config.json (without secrets)${NC}"
        fi
        
        # Use env docker-compose
        if [ ! -f docker-compose.yml ] || [ -L docker-compose.yml ]; then
            ln -sf docker-compose.env.yml docker-compose.yml
            echo -e "${YELLOW}Configured docker-compose.yml for environment variables${NC}"
        fi
        
        echo ""
        echo -e "${YELLOW}IMPORTANT: Edit .env file with your credentials:${NC}"
        echo "  nano .env"
        echo ""
        echo "Then run:"
        echo "  chmod 600 .env"
        echo "  docker-compose up -d"
        ;;
        
    2)
        echo -e "${GREEN}Setting up with Docker Secrets${NC}"
        
        # Check if swarm is initialized
        if ! docker info 2>/dev/null | grep -q "Swarm: active"; then
            echo -e "${YELLOW}Docker Swarm not initialized. Initializing...${NC}"
            docker swarm init
        fi
        
        # Create config without secrets
        if [ ! -f config.json ]; then
            cp config.secure.json config.json
            echo -e "${YELLOW}Created config.json (without secrets)${NC}"
        fi
        
        # Use secrets docker-compose
        if [ ! -f docker-compose.yml ] || [ -L docker-compose.yml ]; then
            ln -sf docker-compose.secrets.yml docker-compose.yml
            echo -e "${YELLOW}Configured docker-compose.yml for Docker secrets${NC}"
        fi
        
        echo ""
        echo -e "${YELLOW}Create Docker secrets:${NC}"
        echo '  echo "your-ksef-token" | docker secret create ksef_token -'
        echo '  echo "your-pushover-user-key" | docker secret create pushover_user_key -'
        echo '  echo "your-pushover-api-token" | docker secret create pushover_api_token -'
        echo ""
        echo "Then deploy:"
        echo "  docker stack deploy -c docker-compose.yml ksef"
        ;;
        
    3)
        echo -e "${YELLOW}WARNING: This method is NOT RECOMMENDED for production!${NC}"
        
        # Create full config
        if [ ! -f config.json ]; then
            cp config.example.json config.json
            echo -e "${YELLOW}Created config.json${NC}"
        fi
        
        # Use standard docker-compose
        echo ""
        echo -e "${YELLOW}Edit config.json with your credentials:${NC}"
        echo "  nano config.json"
        echo ""
        echo "Set secure permissions:"
        echo "  chmod 600 config.json"
        echo ""
        echo "Then run:"
        echo "  docker-compose up -d"
        ;;
        
    *)
        echo -e "${RED}Invalid choice${NC}"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}=================================================="
echo "  Setup complete!"
echo -e "==================================================${NC}"
echo ""
echo "Next steps:"
echo "1. Edit your configuration/secrets as shown above"
echo "2. Build and start the monitor:"
echo "   docker-compose build"
echo "   docker-compose up -d"
echo "3. View logs:"
echo "   docker-compose logs -f"
echo ""
echo "For help, see:"
echo "  README.md - Main documentation"
echo "  SECURITY.md - Security best practices"
echo "  IDE_TROUBLESHOOTING.md - IDE import issues"
echo ""
