# Using Scheduler Nodes as CockroachDB Storage Providers

## Overview
This guide explains how to configure your scheduler nodes to act as CockroachDB storage nodes with controlled disk space allocation.

## Understanding CockroachDB Storage Allocation

### How CockroachDB Distributes Data
CockroachDB **does NOT** use percentage-based allocation like "X% of Y disk space". Instead, it uses:

1. **Available Disk Space**: Primary factor for data placement
2. **Node Capacity**: CPU, memory, and disk I/O
3. **Load Balancing**: Even distribution across nodes
4. **Replication Factor**: Default 3 replicas per range

### Achieving "X% of Y" Behavior

Since CockroachDB doesn't support percentage-based allocation natively, you have several options:

#### Option 1: OS-Level Disk Quotas (Recommended)
Limit disk space at the operating system level before starting CockroachDB:

```bash
# On each scheduler node, create a dedicated partition or use LVM
# Example: Allocate 20% of 500GB = 100GB for CockroachDB

# Using LVM (Logical Volume Manager)
sudo lvcreate -L 100G -n cockroach-data vg0
sudo mkfs.ext4 /dev/vg0/cockroach-data
sudo mkdir -p /var/lib/cockroach
sudo mount /dev/vg0/cockroach-data /var/lib/cockroach

# Or use a dedicated mount point with disk quota
sudo mount -o usrquota,grpquota /dev/sdb1 /var/lib/cockroach
sudo edquota -u cockroach  # Set quota to 100GB
```

#### Option 2: Docker/Container Limits
If running CockroachDB in containers:

```yaml
# docker-compose.yml
services:
  cockroach:
    volumes:
      - cockroach-data:/cockroach/cockroach-data
    deploy:
      resources:
        limits:
          storage: 100G  # 20% of 500GB

volumes:
  cockroach-data:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /path/to/limited/space
```

#### Option 3: Zone Configuration (Influence Placement)
While not percentage-based, you can influence data placement:

```sql
-- Set constraints based on node attributes
ALTER DATABASE peercompute CONFIGURE ZONE USING
  constraints = '[+disk=large: 1]';  -- Prefer nodes with large disk attribute

-- Or use node locality
ALTER DATABASE peercompute CONFIGURE ZONE USING
  constraints = '{"+region=us-east": 1, "+region=us-west": 1}';
```

## Implementation Plan

### Step 1: Prepare Each Scheduler Node

On each scheduler node that will host a CockroachDB node:

```bash
# 1. Calculate disk space allocation
# Example: If node has 500GB and you want 20% for DB
ALLOCATED_SPACE=$((500 * 1024 * 1024 * 1024 * 20 / 100))  # 100GB in bytes

# 2. Create dedicated directory with size limit
sudo mkdir -p /var/lib/cockroach
sudo chown $USER:$USER /var/lib/cockroach

# 3. Option A: Use filesystem quota
sudo mount -o usrquota /dev/sdb1 /var/lib/cockroach
sudo setquota -u $USER 100000000 100000000 0 0 /var/lib/cockroach

# 3. Option B: Use a loop device with limited size
dd if=/dev/zero of=/var/lib/cockroach/disk.img bs=1G count=100  # 100GB
sudo losetup /dev/loop0 /var/lib/cockroach/disk.img
sudo mkfs.ext4 /dev/loop0
sudo mount /dev/loop0 /var/lib/cockroach/data
```

### Step 2: Start CockroachDB Nodes on Scheduler Nodes

#### Node 1 (Scheduler Node 1)
```bash
# Get node IP
NODE1_IP=$(hostname -I | awk '{print $1}')

# Start CockroachDB node
./cockroach start \
  --insecure \
  --advertise-addr=$NODE1_IP \
  --join=$NODE1_IP,$NODE2_IP,$NODE3_IP \
  --store=path=/var/lib/cockroach/data \
  --cache=.25 \
  --max-sql-memory=.25 \
  --locality=region=us-east,node=scheduler1 \
  --background
```

#### Node 2 (Scheduler Node 2)
```bash
NODE2_IP=$(hostname -I | awk '{print $1}')

./cockroach start \
  --insecure \
  --advertise-addr=$NODE2_IP \
  --join=$NODE1_IP,$NODE2_IP,$NODE3_IP \
  --store=path=/var/lib/cockroach/data \
  --cache=.25 \
  --max-sql-memory=.25 \
  --locality=region=us-west,node=scheduler2 \
  --background
```

#### Node 3+ (Additional Scheduler Nodes)
Repeat for each scheduler node with its own IP and locality.

### Step 3: Initialize Cluster

```bash
# On any node
./cockroach init --insecure --host=$NODE1_IP:26257
```

### Step 4: Monitor Disk Usage

```sql
-- Check disk usage per node
SELECT 
  node_id,
  store_id,
  available,
  used,
  (used::float / (available + used) * 100) as usage_percent
FROM crdb_internal.kv_store_status;

-- Check data distribution
SELECT 
  range_id,
  lease_holder,
  replicas,
  range_size
FROM [SHOW RANGES FROM DATABASE peercompute]
ORDER BY range_size DESC;
```

### Step 5: Configure Django to Use CockroachDB

Update `scheduler/scheduler/settings.py`:

```python
# Option 1: Connect to a single node (simplest)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "peercompute",
        "USER": "root",
        "PASSWORD": "",
        "HOST": "<node1-ip>",  # Or use load balancer
        "PORT": "26257",
        "OPTIONS": {
            "sslmode": "disable",
        },
    }
}

# Option 2: Use connection pooling with multiple nodes
# Install django-db-connection-pool or use PgBouncer
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "peercompute",
        "USER": "root",
        "PASSWORD": "",
        "HOST": "cockroach-lb",  # Load balancer in front of nodes
        "PORT": "26257",
        "OPTIONS": {
            "sslmode": "disable",
        },
        "CONN_MAX_AGE": 600,  # Connection pooling
    }
}
```

## Dynamic Disk Space Management

### Script to Calculate and Allocate Space

Create a script that each scheduler node runs to determine its allocation:

```bash
#!/bin/bash
# allocate_db_space.sh

# Get total disk space
TOTAL_SPACE=$(df -BG / | tail -1 | awk '{print $2}' | sed 's/G//')
ALLOCATION_PERCENT=20  # 20% of total

# Calculate allocated space
ALLOCATED_GB=$((TOTAL_SPACE * ALLOCATION_PERCENT / 100))

echo "Total disk space: ${TOTAL_SPACE}GB"
echo "Allocated for CockroachDB: ${ALLOCATED_GB}GB (${ALLOCATION_PERCENT}%)"

# Create limited-size file for CockroachDB
dd if=/dev/zero of=/var/lib/cockroach/disk.img bs=1G count=$ALLOCATED_GB
sudo losetup /dev/loop0 /var/lib/cockroach/disk.img
sudo mkfs.ext4 /dev/loop0
sudo mkdir -p /var/lib/cockroach/data
sudo mount /dev/loop0 /var/lib/cockroach/data
```

### Integration with Scheduler Node Discovery

Since your schedulers are discovered via MQTT, you can extend the discovery to include disk capacity:

```python
# In scheduler discovery logic
def get_node_disk_capacity():
    """Get available disk space for CockroachDB"""
    import shutil
    total, used, free = shutil.disk_usage("/var/lib/cockroach")
    allocation_percent = 20  # 20% of total
    allocated = total * allocation_percent // 100
    return {
        "total": total,
        "allocated": allocated,
        "available": free
    }

# Include in scheduler announcement
scheduler_info = {
    "id": scheduler_id,
    "location": location,
    "disk_capacity": get_node_disk_capacity(),
    "cockroach_node": True
}
```

## Monitoring and Alerts

### Set Up Disk Usage Monitoring

```sql
-- Create a view to monitor disk usage
CREATE VIEW disk_usage_monitor AS
SELECT 
  node_id,
  store_id,
  available / (1024*1024*1024) as available_gb,
  used / (1024*1024*1024) as used_gb,
  (used::float / (available + used) * 100) as usage_percent
FROM crdb_internal.kv_store_status
WHERE usage_percent > 80;  -- Alert if > 80% full
```

### Alert Script

```bash
#!/bin/bash
# check_disk_usage.sh

THRESHOLD=80  # Alert if > 80% full

cockroach sql --insecure -e "
  SELECT node_id, usage_percent 
  FROM disk_usage_monitor 
  WHERE usage_percent > $THRESHOLD
" | while read node_id usage; do
  echo "ALERT: Node $node_id is ${usage}% full!"
  # Send alert via MQTT or email
done
```

## Best Practices

1. **Minimum 3 Nodes**: Always run at least 3 nodes for production
2. **Replication Factor**: Keep default (3) for fault tolerance
3. **Disk Monitoring**: Monitor disk usage and set up alerts
4. **Backup Strategy**: Regular backups before migration
5. **Test First**: Test migration on a small subset of data
6. **Connection Pooling**: Use PgBouncer or Django connection pooling
7. **Load Balancing**: Use a load balancer in front of CockroachDB nodes

## Troubleshooting

### Node Running Out of Space
```sql
-- Check which tables are using most space
SELECT 
  table_name,
  range_count,
  SUM(range_size) as total_size
FROM [SHOW RANGES FROM DATABASE peercompute]
GROUP BY table_name
ORDER BY total_size DESC;
```

### Rebalancing Data
CockroachDB automatically rebalances, but you can trigger manually:
```sql
-- Set zone config to force rebalancing
ALTER DATABASE peercompute CONFIGURE ZONE USING
  num_replicas = 3,
  lease_preferences = '[[+region=us-east]]';
```

## Next Steps

1. **Test Setup**: Start with 3 nodes on test machines
2. **Import Data**: Use your cleaned SQL dump
3. **Test Django**: Verify all operations work
4. **Monitor**: Set up monitoring and alerts
5. **Scale**: Add more scheduler nodes as needed


