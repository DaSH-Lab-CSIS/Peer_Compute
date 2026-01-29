# CockroachDB Resources and Learning

## Official Documentation
- **Migration Guide**: https://www.cockroachlabs.com/docs/stable/migrate-from-postgres.html
- **Import Data**: https://www.cockroachlabs.com/docs/stable/import.html
- **Zone Configuration**: https://www.cockroachlabs.com/docs/stable/configure-replication-zones.html
- **Django Setup**: https://www.cockroachlabs.com/docs/stable/build-a-python-app-with-cockroachdb-django.html

## Key Concepts for Your Use Case

### 1. Data Distribution
CockroachDB automatically distributes data across nodes:
- **Ranges**: Data is split into 512MB ranges
- **Replication**: Each range replicated 3x (default)
- **Automatic Rebalancing**: When nodes added/removed

### 2. Storage Allocation
Unlike percentage-based allocation, CockroachDB uses:
- **Available disk space** (primary factor)
- **Node capacity** (CPU, memory)
- **Load balancing** (even distribution)

To achieve "X% of Y disk space" behavior:
- Configure disk quotas at OS level
- Use zone configs to control placement
- Monitor and adjust manually

### 3. PostgreSQL Compatibility
CockroachDB is PostgreSQL-compatible but has differences:
- **Serializable isolation** (stronger than PostgreSQL's default)
- **Some SQL features** may differ
- **Performance characteristics** may vary

## Cloning CockroachDB Repo (Optional)

If you want to understand internals:

```bash
git clone https://github.com/cockroachdb/cockroach.git
cd cockroach
```

Key directories:
- `pkg/kv/` - Key-value storage layer
- `pkg/sql/` - SQL layer
- `pkg/server/` - Server implementation
- `pkg/roachpb/` - Protocol buffers

**Note**: Building from source requires Go toolchain and is complex. For migration, use official binaries.

## Alternative: Using CockroachDB Cloud

If you don't want to manage infrastructure:
- **CockroachDB Cloud**: Managed service
- **CockroachDB Dedicated**: AWS/GCP managed
- Still distributed, but managed by Cockroach Labs

## Your Specific Architecture

### Current System
- Multiple scheduler nodes (identified by `location`)
- Each node can contribute resources
- Need distributed database for scalability

### With CockroachDB
- Each scheduler node can run a CockroachDB node
- Data automatically distributed
- Survives node failures
- Scales horizontally

### Configuration Example
```python
# settings.py - Multiple database connections for load balancing
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "peercompute",
        "USER": "root",
        "PASSWORD": "",
        "HOST": "cockroach-lb.example.com",  # Load balancer
        "PORT": "26257",
        "OPTIONS": {"sslmode": "disable"},
    },
    # Or use multiple hosts with connection pooling
}
```

## Monitoring and Management

### Useful CockroachDB SQL Commands
```sql
-- Check cluster status
SHOW CLUSTER SETTING cluster.organization;
SHOW CLUSTER SETTING cluster.name;

-- Check node status
SHOW NODES;

-- Check database size
SELECT * FROM [SHOW RANGES FROM DATABASE peercompute];

-- Check table distribution
SELECT * FROM [SHOW RANGES FROM TABLE profiles_user];

-- Check replication status
SELECT * FROM crdb_internal.ranges WHERE database_name = 'peercompute';
```

## Performance Tuning

1. **Connection Pooling**: Use PgBouncer or CockroachDB's built-in pooler
2. **Indexes**: Ensure proper indexes (CockroachDB creates primary key indexes automatically)
3. **Zone Configs**: Tune replication and placement
4. **Query Optimization**: Use EXPLAIN ANALYZE

## Next Steps

1. **Read official docs** (linked above)
2. **Set up test cluster** (3 nodes minimum)
3. **Test migration** with sample data
4. **Benchmark performance**
5. **Plan production migration**


