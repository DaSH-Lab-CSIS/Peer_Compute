# CockroachDB Migration Documentation

This directory contains comprehensive documentation for migrating from Supabase PostgreSQL to a distributed CockroachDB cluster using scheduler nodes as database storage providers.

## Documentation Overview

### 📋 [MIGRATION_FAQ.md](./MIGRATION_FAQ.md)
**Start here!** Direct answers to your questions:
- Do I need a single instance first? (No)
- How does PostgreSQL migrate to distributed? (Automatic)
- Should I clone the repo? (Helpful but not required)
- How to achieve X% disk allocation? (OS-level quotas)

### 📘 [cockroachdb_migration_plan.md](./cockroachdb_migration_plan.md)
Complete step-by-step migration guide:
- Phase 1: Setup CockroachDB cluster
- Phase 2: Data migration from Supabase
- Phase 3: Django configuration
- Phase 4: Data distribution configuration
- Testing checklist and rollback plan

### 💾 [scheduler_nodes_as_db_storage.md](./scheduler_nodes_as_db_storage.md)
Detailed guide on using scheduler nodes as storage:
- Understanding CockroachDB storage allocation
- Implementing "X% of Y disk space" behavior
- OS-level disk quotas and container limits
- Dynamic disk space management scripts
- Monitoring and alerts

### 📚 [cockroachdb_resources.md](./cockroachdb_resources.md)
Resources and learning materials:
- Official documentation links
- Key concepts for your use case
- Monitoring SQL commands
- Performance tuning tips

## Quick Start

1. **Read the FAQ** → `MIGRATION_FAQ.md` for quick answers
2. **Review migration plan** → `cockroachdb_migration_plan.md` for steps
3. **Configure storage** → `scheduler_nodes_as_db_storage.md` for disk allocation
4. **Reference resources** → `cockroachdb_resources.md` for docs and commands

## Current Status

Based on your setup, you have:
- ✅ CockroachDB repo cloned
- ✅ SQL dump files ready (`supabase_dump.sql`, `supabase_dump_cleaned.sql`)
- ✅ Cleaning script (`clean_dump.sh`)
- ✅ Single node running (node1)

**Next Steps:**
1. Set up multi-node cluster (3+ nodes)
2. Import cleaned SQL dump
3. Update Django settings
4. Test and monitor

## Architecture Overview

```
┌─────────────────┐
│  Load Balancer  │
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
┌───▼───┐ ┌───▼───┐ ┌───▼───┐
│Sched1 │ │Sched2 │ │Sched3 │
│       │ │       │ │       │
│CockDB │ │CockDB │ │CockDB │
│ Node  │ │ Node  │ │ Node  │
└───┬───┘ └───┬───┘ └───┬───┘
    │         │         │
    └────┬────┴────┬────┘
         │         │
    ┌────▼─────────▼────┐
    │  CockroachDB      │
    │  Distributed DB   │
    │  (Auto-distributed)│
    └───────────────────┘
```

Each scheduler node runs a CockroachDB node, and data is automatically distributed across all nodes.

## Key Concepts

### Data Distribution
- CockroachDB splits data into **512MB ranges**
- Each range replicated **3x** (default)
- Distribution is **automatic** based on available space
- **No manual sharding** required

### Storage Allocation
- CockroachDB uses **available disk space** (not percentages)
- Use **OS-level quotas** to limit disk space per node
- Distribution is **proportional** to available space

### PostgreSQL Compatibility
- CockroachDB is **wire-compatible** with PostgreSQL
- Django works **as-is** (no code changes needed)
- Some PostgreSQL features may differ (check docs)

## Migration Strategy

### Option A: Direct Multi-Node (Recommended)
1. Set up 3+ nodes from start
2. Initialize cluster
3. Import data
4. Data automatically distributes

### Option B: Single Node First
1. Start with 1 node
2. Import data
3. Add nodes
4. CockroachDB rebalances automatically

**Recommendation:** Use Option A for cleaner migration.

## Important Notes

⚠️ **Minimum 3 nodes** for production (fault tolerance)
⚠️ **Test thoroughly** before production migration
⚠️ **Keep Supabase running** during migration for rollback
⚠️ **Monitor disk usage** - set up alerts
⚠️ **Use connection pooling** for Django

## Getting Help

- **Official Docs**: https://www.cockroachlabs.com/docs/
- **Migration Guide**: https://www.cockroachlabs.com/docs/stable/migrate-from-postgres.html
- **Django Setup**: https://www.cockroachlabs.com/docs/stable/build-a-python-app-with-cockroachdb-django.html

## Files in This Directory

```
migration_docs/
├── README.md (this file)
├── MIGRATION_FAQ.md
├── cockroachdb_migration_plan.md
├── scheduler_nodes_as_db_storage.md
└── cockroachdb_resources.md
```

