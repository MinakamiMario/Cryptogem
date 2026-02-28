# Lab Deployment

## macOS (launchd)

```bash
# Copy plist
cp lab/deploy/com.cryptogem.lab.plist ~/Library/LaunchAgents/

# Create log directory
mkdir -p lab/logs

# Load (start on boot)
launchctl load ~/Library/LaunchAgents/com.cryptogem.lab.plist

# Unload (stop)
launchctl unload ~/Library/LaunchAgents/com.cryptogem.lab.plist

# Check status
launchctl list | grep cryptogem
```

## Linux (systemd)

```bash
# Copy service file
sudo cp lab/deploy/lab.service /etc/systemd/system/

# Create log directory
mkdir -p lab/logs

# Enable and start
sudo systemctl enable cryptogem-lab
sudo systemctl start cryptogem-lab

# Check status
sudo systemctl status cryptogem-lab
```

## Crontab alternative (Linux)

```bash
# Run every 24h at 00:00 UTC
0 0 * * * cd /home/oussama/Cryptogem && /usr/bin/python3 -m lab.main run --hours 24 >> lab/logs/lab.stdout.log 2>&1
```
