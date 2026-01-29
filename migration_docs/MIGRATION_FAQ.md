# CockroachDB Migration FAQ

## Direct Answers to Your Questions

### Q1: Do I need to migrate to a single Cockroach instance first, then distribute?

**Answer: NO** - You can migrate directly to a multi-node cluster.

**Recommended Approach:**
1. Set up 3+ CockroachDB nodes (one per scheduler node or dedicated nodes)
2. Initialize the cluster with all nodes from the start
3. Import data directly into the cluster
4. CockroachDB will automatically distribute data across nodes

**Why this is better:**
- Data is distributed from the beginning
- No rebalancing overhead after migration
- Matches your distributed architecture
- Faster overall migration process

**Alternative (if you must):**
- Start with 1 node, import data, then add nodes
- CockroachDB will automatically rebalance data when nodes are added
- More overhead but still works

### Q2: How does a single PostgreSQL DB migrate to distributed?

**Answer:** CockroachDB is PostgreSQL-compatible, so migration is straightforward:

**Migration Process:**
1. **Export from Supabase:**
   ```bash
   pg_dump -h aws-0-ap-south-1.pooler.supabase.com \
     -U postgres.uufnsxmqnwegackubear \
     -d postgres \
     --no-owner --no-privileges \
     -f supabase_dump.sql
   ```

2. **Clean the dump** (you already have `clean_dump.sh`):
   ```bash
   ./clean_dump.sh  # Removes PostgreSQL-specific features
   ```

3. **Import to CockroachDB:**
   ```bash
   # Create database
   cockroach sql --insecure -e "CREATE DATABASE peercompute;"
   
   # Import (using IMPORT PGDUMP or direct SQL)
   cockroach sql --insecure -d peercompute < supabase_dump_cleaned.sql
   ```

4. **Data automatically distributes:**
   - CockroachDB splits data into 512MB ranges
   - Each range is replicated 3x (default)
   - Ranges are distributed across nodes automatically
   - No manual distribution needed!

**What gets distributed:**
- Tables are split into ranges
- Each range stored on different nodes
- Replicas stored on different nodes for fault tolerance
- Automatic load balancing

### Q3: Will cloning CockroachDB repo help?

**Answer: Helpful for learning, NOT required for migration.**

**You've already cloned it** - I can see you have:
- `cockroach/` directory with source code
- Setup guides
- SQL dump files
- A working node1 instance

**When the repo is useful:**
- ✅ Understanding internal architecture
- ✅ Learning how distributed systems work
- ✅ Customizing behavior (advanced)
- ✅ Contributing to CockroachDB

**When it's NOT needed:**
- ❌ Basic migration (use official binaries)
- ❌ Production deployment (use official releases)
- ❌ Standard operations (use official docs)

**Recommendation:**
- Use official binaries for migration: `wget https://binaries.cockroachdb.com/cockroach-v23.2.0.linux-amd64.tgz`
- Keep the repo for reference and learning
- Focus on migration using official documentation

### Q4: How to use scheduler nodes as disk providers with X% allocation?

**Answer: CockroachDB doesn't support percentage-based allocation natively, but you can achieve it:**

**The Challenge:**
- CockroachDB uses **available disk space** as the primary factor
- It doesn't have a "use X% of Y" feature
- Distribution is automatic based on capacity

**Solutions:**

#### Solution 1: OS-Level Disk Quotas (Best)
```bash
# On each scheduler node
# Allocate 20% of 500GB = 100GB for CockroachDB

# Create limited-size filesystem
dd if=/dev/zero of=/var/lib/cockroach/disk.img bs=1G count=100
sudo losetup /dev/loop0 /var/lib/cockroach/disk.img
sudo mkfs.ext4 /dev/loop0
sudo mount /dev/loop0 /var/lib/cockroach/data

# Start CockroachDB with this mount point
./cockroach start --store=path=/var/lib/cockroach/data ...
```

#### Solution 2: LVM with Size Limits
```bash
# Create logical volume with specific size
sudo lvcreate -L 100G -n cockroach-data vg0
sudo mkfs.ext4 /dev/vg0/cockroach-data
sudo mount /dev/vg0/cockroach-data /var/lib/cockroach/data
```

#### Solution 3: Docker/Container Limits
```yaml
services:
  cockroach:
    deploy:
      resources:
        limits:
          storage: 100G  # Hard limit
```

**How CockroachDB Distributes:**
- If Node 1 has 100GB allocated → gets ~33% of data
- If Node 2 has 200GB allocated → gets ~66% of data  
- If Node 3 has 100GB allocated → gets ~33% of data
- Distribution is proportional to available space

**Monitoring Allocation:**
```sql
-- Check actual disk usage per node
SELECT 
  node_id,
  available / (1024*1024*1024) as available_gb,
  used / (1024*1024*1024) as used_gb,
  (used::float / (available + used) * 100) as usage_percent
FROM crdb_internal.kv_store_status;
```

## Migration Checklist

Based on what you've already done:

- [x] Cloned CockroachDB repo
- [x] Created setup guide
- [x] Exported Supabase dump
- [x] Created cleaning script
- [x] Started single node (node1 exists)
- [ ] Set up multi-node cluster
- [ ] Import cleaned SQL dump
- [ ] Test Django connection
- [ ] Configure disk space limits
- [ ] Set up monitoring
- [ ] Test failover
- [ ] Production migration

## Quick Start: Multi-Node Setup

Since you already have node1 running, here's how to expand:

```bash
# Stop current single node
# (Ctrl-C in the terminal running it)

# Start node1 (first scheduler)
./cockroach start \
  --insecure \
  --advertise-addr=<node1-ip> \
  --store=path=node1 \
  --join=<node1-ip>,<node2-ip>,<node3-ip> \
  --locality=node=scheduler1

# Start node2 (second scheduler - different machine)
./cockroach start \
  --insecure \
  --advertise-addr=<node2-ip> \
  --store=path=node2 \
  --join=<node1-ip>,<node2-ip>,<node3-ip> \
  --locality=node=scheduler2

# Start node3 (third scheduler - different machine)
./cockroach start \
  --insecure \
  --advertise-addr=<node3-ip> \
  --store=path=node3 \
  --join=<node1-ip>,<node2-ip>,<node3-ip> \
  --locality=node=scheduler3

# Initialize cluster
./cockroach init --insecure --host=<node1-ip>:26257
```

## Next Steps

1. **Review your cleaned SQL dump** - Make sure it's ready
2. **Set up 3 scheduler nodes** - One CockroachDB node per scheduler
3. **Configure disk limits** - Use one of the solutions above
4. **Import data** - Use your cleaned dump
5. **Update Django settings** - Point to CockroachDB cluster
6. **Test thoroughly** - Especially ILP scheduling logic
7. **Monitor and tune** - Watch disk usage and performance

## Key Takeaways

1. ✅ **No need for single-node first** - Go straight to multi-node
2. ✅ **Migration is straightforward** - PostgreSQL compatibility makes it easy
3. ✅ **Repo is helpful but not required** - Use official binaries for migration
4. ✅ **X% allocation via OS-level limits** - Not built into CockroachDB, but achievable
5. ✅ **Automatic distribution** - CockroachDB handles it once data is imported

## Documentation Created

1. `cockroachdb_migration_plan.md` - Complete migration steps
2. `cockroachdb_resources.md` - Resources and learning materials
3. `scheduler_nodes_as_db_storage.md` - Detailed disk allocation guide
4. `MIGRATION_FAQ.md` - This document (answers to your questions)

All documents are in `Serverless_Scheduler/migration_docs/`

