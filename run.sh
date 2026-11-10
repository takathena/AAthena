#!/bin/bash
# AAguard IoT - Quick Run Script

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

if [ ! -d "venv" ]; then
    echo -e "${RED}Virtualenv tidak ada. Jalankan: make dev${NC}"
    exit 1
fi

if [ ! -f ".env" ]; then
    echo -e "${RED}.env tidak ada. Copy dari .env.example${NC}"
    exit 1
fi

source venv/bin/activate

PORT=$(grep '^PORT' .env | cut -d= -f2 | tr -d ' ' || echo 5000)
echo -e "${GREEN}Starting AAguard IoT...${NC}"
echo -e "${YELLOW}   Akses: http://localhost:${PORT}${NC}"
echo ""

exec python -u run.py