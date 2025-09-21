#!/bin/bash

# Activate virtual environment
source .venv/bin/activate

# Run provider with proper environment
sudo -E env "PATH=$PATH" "VIRTUAL_ENV=$VIRTUAL_ENV" python provider/provider1.py "$1"
