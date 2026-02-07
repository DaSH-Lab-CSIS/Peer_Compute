#!/bin/bash

if [ "$#" -ne 1 ]; then
    echo "Error: Invalid number of arguments."
    echo "Usage: ./keygen_to_all.sh <filename.txt>"
    exit 1
fi

HOSTS_FILE="$1"

if [ ! -f "$HOSTS_FILE" ]; then
    echo "Error: File '$HOSTS_FILE' not found."
    exit 1
fi

if [ ! -f ~/.ssh/id_rsa.pub ]; then
    echo "Generating key pair..."
    ssh-keygen -t rsa -b 4096 -N "" -f ~/.ssh/id_rsa
fi

PUB_KEY=$(cat ~/.ssh/id_rsa.pub)

if [[ "$HOSTS_FILE" == *"cortalims"* ]]; then
    echo "Target: Cortalim Nodes"
    echo "Suggestion: Use password 'raspberry'"
elif [[ "$HOSTS_FILE" == *"palolems"* ]]; then
    echo "Target: Palolem Nodes"
    echo "Suggestion: Use password 'nvidia'"
fi

read -s -p "Enter SSH password for nodes in $HOSTS_FILE: " USER_PASS
echo -e "\n"

while read -r host || [ -n "$host" ]; do
    [[ -z "$host" || "$host" =~ ^# ]] && continue

    echo "------------------------------------------------"
    echo "Processing: $host"
    
    # ADDED: < /dev/null 
    # This prevents SSH from consuming the rest of your .txt file.
    sshpass -p "$USER_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 "$host" \
    "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '$PUB_KEY' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys" < /dev/null
    
    if [ $? -eq 0 ]; then
        echo "SUCCESS: Key installed on $host"
    else
        echo "FAILED: Could not reach or authenticate with $host"
    fi
done < "$HOSTS_FILE"

echo -e "\n--- Distribution Task Complete ---"
