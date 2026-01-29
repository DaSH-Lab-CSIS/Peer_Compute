# MQTT Dashboard - Remote Access Guide

## Overview

The MQTT Dashboard runs on port 9020 by default. To access it from a different network, you have several options:

## Option 1: SSH Port Forwarding (Recommended)

This is the most secure and common method. It creates an encrypted tunnel through SSH.

### From Your Local Machine (where you want to view the dashboard):

**Basic command:**
```bash
ssh -L 9020:localhost:9020 user@remote-machine-ip
```

**With ProxyJump (Jump Node):**
```bash
ssh -L 9020:localhost:9020 colva2peercompute
```

**If port 9020 is already in use on your local machine, use a different port:**
```bash
ssh -L 8080:localhost:9020 colva2peercompute
```
Then access: `http://localhost:8080`

### Background SSH Tunnel (keeps running after closing terminal):

```bash
ssh -f -N -L 8080:localhost:9020 colva2peercompute
```

- `-f`: Run in background
- `-N`: Don't execute remote commands
- `-L`: Local port forwarding

To stop the background tunnel:
```bash
# Windows PowerShell
Get-Process | Where-Object {$_.ProcessName -eq "ssh"} | Stop-Process

# Or find and kill specific SSH process
netstat -ano | findstr :8080
taskkill /PID <PID> /F
```

### Troubleshooting Port Binding Issues

**"Permission denied" or "Address already in use":**

1. **Check if port is in use:**
   ```powershell
   # Windows PowerShell
   netstat -ano | findstr :9020
   ```

2. **Use a different local port:**
   ```bash
   ssh -L 8080:localhost:9020 colva2peercompute
   # or
   ssh -L 9021:localhost:9020 colva2peercompute
   ```

3. **Check if you need admin privileges** (unlikely for ports > 1024):
   - Right-click PowerShell/Command Prompt → "Run as Administrator"

4. **Kill process using the port** (if found):
   ```powershell
   # Find PID from netstat output, then:
   taskkill /PID <PID> /F
   ```

## Option 2: Public IP with Firewall Rules

If the machine running the dashboard has a public IP address:

1. **Ensure dashboard is listening on all interfaces** (already configured):
   ```bash
   uvicorn mqtt_dashboard:app --host 0.0.0.0 --port 9020
   ```

2. **Open firewall port** (if firewall is enabled):
   ```bash
   # Ubuntu/Debian
   sudo ufw allow 9020/tcp
   
   # CentOS/RHEL
   sudo firewall-cmd --add-port=9020/tcp --permanent
   sudo firewall-cmd --reload
   ```

3. **Access from browser**:
   ```
   http://<public-ip>:9020
   ```

**Security Note:** This exposes the dashboard to the internet. Consider adding authentication or restricting access by IP.

## Option 3: VPN Connection

If both machines are on the same VPN:

1. Connect both machines to the VPN
2. Access the dashboard using the VPN IP:
   ```
   http://<vpn-ip>:9020
   ```

## Option 4: Reverse SSH Tunnel (if you can't SSH directly)

If the remote machine is behind NAT/firewall and you can't SSH directly:

### On the remote machine (running dashboard):
```bash
ssh -R 9020:localhost:9020 user@your-local-machine-ip
```

Then access on your local machine: `http://localhost:9020`

## Option 5: Cloud Deployment

Deploy the dashboard to a cloud service (AWS, GCP, Azure, etc.) with a public IP:

1. Deploy `mqtt_dashboard.py` to cloud instance
2. Ensure security groups allow port 9020
3. Access via public IP: `http://<cloud-ip>:9020`

## Quick Test

To verify the dashboard is accessible:

### On the machine running the dashboard:
```bash
# Check if it's listening
netstat -tuln | grep 9020
# or
ss -tuln | grep 9020
```

### From another machine on the same network:
```bash
curl http://<dashboard-machine-ip>:9020/api/stats
```

## Troubleshooting

### "Connection refused"
- Check if dashboard is running: `ps aux | grep mqtt_dashboard`
- Check if listening on correct interface: `netstat -tuln | grep 9020`
- Check firewall rules

### "Can't connect via SSH"
- Verify SSH is enabled on remote machine
- Check SSH port (default 22)
- Verify network connectivity

### "Dashboard loads but no messages"
- Check MQTT broker connectivity from the dashboard machine
- Verify MQTT broker is accessible: `telnet broker.hivemq.com 1883`
- Check dashboard logs for MQTT connection errors

### "Permission denied" on port binding (Windows)
- Port is likely already in use
- Use a different local port (8080, 9021, etc.)
- Check with: `netstat -ano | findstr :9020`
- Kill process if needed: `taskkill /PID <PID> /F`

## Security Considerations

1. **SSH Port Forwarding** - Most secure, encrypted tunnel
2. **Public IP Access** - Consider adding:
   - Basic authentication
   - IP whitelisting
   - HTTPS/SSL
3. **VPN** - Secure if VPN is properly configured
4. **Cloud Deployment** - Use security groups and authentication

## Example: Complete SSH Tunnel Setup with ProxyJump

```bash
# Terminal 1: SSH tunnel (keep this running)
# Use a different port if 9020 is in use
ssh -L 8080:localhost:9020 colva2peercompute

# Terminal 2: On colva2, start dashboard (if not already running)
cd /home/peercompute/Serverless_Scheduler_sn34kyp3t3
uvicorn mqtt_dashboard:app --host 0.0.0.0 --port 9020

# Browser: On your local Windows machine
# Open: http://localhost:8080
```

## Environment Variables for Remote Access

You can also configure the dashboard host/port via environment variables:

```bash
export DASHBOARD_PORT=9020
export MQTT_BROKER=broker.hivemq.com
uvicorn mqtt_dashboard:app --host 0.0.0.0 --port $DASHBOARD_PORT
```
