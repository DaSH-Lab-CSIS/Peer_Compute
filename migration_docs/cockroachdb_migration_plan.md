# CockroachDB Migration Plan

## Overview
Migrate from Supabase PostgreSQL to a distributed CockroachDB cluster using scheduler nodes as database storage providers.

## Architecture

### Current Setup
- **Database**: Supabase PostgreSQL (single instance)
- **Scheduler Nodes**: Multiple nodes identified by `location` field
- **Django ORM**: Using `django.db.backends.postgresql`

### Target Setup
- **Database**: CockroachDB cluster (3+ nodes)
- **Storage**: Each scheduler node contributes disk space
- **Django ORM**: Continue using `django.db.backends.postgresql` (CockroachDB is PostgreSQL-compatible)

## Migration Strategy

### Phase 1: Setup CockroachDB Cluster

#### 1.1 Install CockroachDB on Scheduler Nodes
```bash
# On each scheduler node
wget -qO- https://binaries.cockroachdb.com/cockroach-v23.2.0.linux-amd64.tgz | tar xvz
sudo cp cockroach-v23.2.0.linux-amd64/cockroach /usr/local/bin/
```

#### 1.2 Initialize First Node
```bash
# On scheduler node 1
cockroach start \
  --insecure \
  --advertise-addr=<node1-ip> \
  --join=<node1-ip>,<node2-ip>,<node3-ip> \
  --cache=.25 \
  --max-sql-memory=.25 \
  --store=path=/path/to/cockroach-data \
  --background
```

#### 1.3 Initialize Additional Nodes
```bash
# On scheduler node 2
cockroach start \
  --insecure \
  --advertise-addr=<node2-ip> \
  --join=<node1-ip>,<node2-ip>,<node3-ip> \
  --cache=.25 \
  --max-sql-memory=.25 \
  --store=path=/path/to/cockroach-data \
  --background

# Repeat for node 3, 4, etc.
```

#### 1.4 Initialize Cluster
```bash
# On any node
cockroach init --insecure --host=<node1-ip>:26257
```

### Phase 2: Data Migration

#### 2.1 Export from Supabase
```bash
# Export schema
pg_dump -h aws-0-ap-south-1.pooler.supabase.com \
  -U postgres.uufnsxmqnwegackubear \
  -d postgres \
  --schema-only \
  -f schema.sql

# Export data
pg_dump -h aws-0-ap-south-1.pooler.supabase.com \
  -U postgres.uufnsxmqnwegackubear \
  -d postgres \
  --data-only \
  --no-owner \
  --no-privileges \
  -f data.sql
```

#### 2.2 Prepare SQL for CockroachDB
CockroachDB is mostly PostgreSQL-compatible, but you may need to:
- Remove unsupported features (if any)
- Adjust sequences/auto-increment fields
- Review JSON field usage (should work as-is)

#### 2.3 Import to CockroachDB
```bash
# Create database
cockroach sql --insecure --host=<node1-ip>:26257 -e "CREATE DATABASE peercompute;"

# Import schema
cockroach sql --insecure --host=<node1-ip>:26257 -d peercompute < schema.sql

# Import data
cockroach sql --insecure --host=<node1-ip>:26257 -d peercompute < data.sql
```

### Phase 3: Django Configuration

#### 3.1 Update settings.py
```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "peercompute",
        "USER": "root",
        "PASSWORD": "",  # Or use secure mode with certificates
        "HOST": "<cockroach-node1-ip>",  # Or use load balancer
        "PORT": "26257",
        "OPTIONS": {
            "sslmode": "disable",  # For insecure mode
            # For secure mode:
            # "sslmode": "verify-full",
            # "sslcert": "/path/to/client.crt",
            # "sslkey": "/path/to/client.key",
            # "sslrootcert": "/path/to/ca.crt",
        },
    }
}
```

#### 3.2 Connection Pooling
Consider using a connection pooler (like PgBouncer) or CockroachDB's built-in connection pooling.

### Phase 4: Data Distribution Configuration

#### 4.1 Zone Configuration (Optional)
Control data placement across nodes:

```sql
-- Create zones for different data types
ALTER DATABASE peercompute CONFIGURE ZONE USING
  num_replicas = 3,
  constraints = '{"+region=us-east-1": 1, "+region=us-west-1": 1, "+region=eu-west-1": 1}';

-- Or configure per-table
ALTER TABLE profiles_user CONFIGURE ZONE USING
  num_replicas = 3;
```

#### 4.2 Monitor Distribution
```sql
-- Check range distribution
SELECT * FROM [SHOW RANGES FROM TABLE profiles_user];

-- Check node status
SELECT * FROM [SHOW NODES];
```

## Important Considerations

### 1. Disk Space Management
- CockroachDB automatically distributes data based on available space
- Each node should have sufficient disk space
- Monitor disk usage: `SELECT * FROM [SHOW RANGES] WHERE "range_size" > '100MB';`

### 2. Replication Factor
- Default: 3 replicas (survives 1 node failure)
- Minimum: 3 nodes for production
- Can be adjusted per-database or per-table

### 3. Django Model Compatibility
Your current models should work with minimal changes:
- `UUIDField` - ✅ Supported
- `JSONField` - ✅ Supported
- `DateTimeField` - ✅ Supported
- `ForeignKey` - ✅ Supported
- `CheckConstraint` - ✅ Supported (with some limitations)

### 4. Transaction Behavior
- CockroachDB uses serializable isolation (stronger than PostgreSQL default)
- Some Django patterns may need adjustment
- Test thoroughly with your ILP scheduling logic

### 5. Performance Considerations
- CockroachDB may have different performance characteristics
- Monitor query performance
- Consider using `SELECT FOR UPDATE` carefully (works but may have different behavior)

## Testing Checklist

- [ ] CockroachDB cluster initialized
- [ ] Data migrated successfully
- [ ] Django migrations run
- [ ] Basic CRUD operations work
- [ ] ILP scheduling logic works
- [ ] Job creation/updates work
- [ ] Provider state management works
- [ ] Transaction isolation tested
- [ ] Performance benchmarks run
- [ ] Failover tested (kill a node)

## Rollback Plan

If migration fails:
1. Keep Supabase instance running
2. Switch Django settings back to Supabase
3. Investigate issues
4. Retry migration

## Next Steps

1. Set up test CockroachDB cluster (3 nodes minimum)
2. Export test data from Supabase
3. Import to CockroachDB
4. Test Django application
5. Performance testing
6. Production migration

## Related Documentation

- **MIGRATION_FAQ.md** - Answers to common questions about migration strategy
- **scheduler_nodes_as_db_storage.md** - Detailed guide on using scheduler nodes as storage providers with disk space management
- **cockroachdb_resources.md** - Resources, documentation links, and learning materials

## Quick Reference

### Key Commands
```bash
# Start multi-node cluster
./cockroach start --insecure --store=path=node1 --join=node1,node2,node3

# Initialize cluster
./cockroach init --insecure --host=node1:26257

# Import SQL dump
cockroach sql --insecure -d peercompute < supabase_dump_cleaned.sql

# Check cluster status
cockroach sql --insecure -e "SHOW NODES;"
```

### Important Notes
- Minimum 3 nodes for production
- CockroachDB automatically distributes data
- PostgreSQL-compatible (Django works as-is)
- Use OS-level disk quotas for percentage-based allocation


  