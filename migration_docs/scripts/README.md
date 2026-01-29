# Migration Scripts

This directory contains all scripts needed for migrating from Supabase PostgreSQL to CockroachDB.

## Script Organization

### Phase 1: Preparation
- `export_supabase.sh` - Export data from Supabase
- `clean_dump.sh` - Clean SQL dump for CockroachDB compatibility
- `install_cockroach.sh` - Install CockroachDB on a single node
- `install_cockroach_remote.py` - Install CockroachDB on all nodes remotely
- `setup_disk_allocation.sh` - Setup disk allocation on a single node
- `setup_disk_allocation_remote.py` - Setup disk allocation on all nodes remotely

### Phase 2: Cluster Initialization
- `get_node_ips.py` - Extract node information from .ssh.config
- `start_cockroach_node.sh` - Start a single CockroachDB node
- `start_cockroach_cluster.py` - Start CockroachDB cluster on all nodes
- `init_cluster.sh` - Initialize the cluster (run once after all nodes start)
- `check_cluster_health.sh` - Check cluster health and status

### Phase 3: Data Migration
- `create_database.sh` - Create database in CockroachDB
- `import_schema.sh` - Import schema from cleaned SQL dump
- `import_data.sh` - Import data from cleaned SQL dump
- `verify_data.py` - Verify data migration (compare Supabase vs CockroachDB)
- `check_distribution.sh` - Check data distribution across nodes

### Phase 4: Django Configuration
- `test_django_connection.py` - Test Django connection to CockroachDB

### Phase 5: Testing
- `test_scheduler_operations.py` - Test scheduler operations with CockroachDB
- `benchmark_queries.py` - Benchmark query performance
- `test_failover.sh` - Test cluster failover scenarios

### Phase 6 & 7: Operations
- `monitor_cluster.py` - Monitor cluster health continuously
- `manage_cluster.py` - Cluster management tool (start/stop/status)
- `backup_cluster.sh` - Backup cluster
- `restore_cluster.sh` - Restore cluster from backup

## Quick Start

### 1. Export and Prepare Data
```bash
# Export from Supabase
./export_supabase.sh

# Clean the dump
./clean_dump.sh
```

### 2. Setup Nodes
```bash
# Get node inventory
python get_node_ips.py

# Install CockroachDB on all nodes
python install_cockroach_remote.py

# Setup disk allocation
python setup_disk_allocation_remote.py
```

### 3. Start Cluster
```bash
# Start all nodes
python start_cockroach_cluster.py

# Initialize cluster (run once)
./init_cluster.sh <first-node-ip>
```

### 4. Migrate Data
```bash
# Create database
./create_database.sh <node-ip>

# Import schema
./import_schema.sh <node-ip> 26257 peercompute

# Import data
./import_data.sh <node-ip> 26257 peercompute

# Verify migration
python verify_data.py --cockroach-host <node-ip>
```

### 5. Test Django
```bash
# Test connection
python test_django_connection.py

# Test operations
python test_scheduler_operations.py
```

## Usage Examples

### Check Cluster Status
```bash
./check_cluster_health.sh <node-ip>
python manage_cluster.py status
```

### Monitor Cluster
```bash
python monitor_cluster.py --host <node-ip> --interval 30
```

### Backup and Restore
```bash
# Backup
./backup_cluster.sh <node-ip> 26257 peercompute

# Restore
./restore_cluster.sh <node-ip> 26257 peercompute <backup-path>
```

## Configuration

Most scripts use environment variables or command-line arguments for configuration:

- `COCKROACH_HOST` - CockroachDB host (default: localhost)
- `COCKROACH_PORT` - CockroachDB port (default: 26257)
- `COCKROACH_DB` - Database name (default: peercompute)

For remote scripts, they use:
- `.ssh.config` - SSH configuration file
- `.env` - Environment file with passwords (optional, SSH keys preferred)

## Notes

- All scripts are executable and have been made executable with `chmod +x`
- Python scripts require Python 3.6+
- Bash scripts require standard Unix utilities
- Remote scripts use SSH keys by default (passwords only if keys unavailable)
- Most scripts have `--help` or `-h` flag for usage information
