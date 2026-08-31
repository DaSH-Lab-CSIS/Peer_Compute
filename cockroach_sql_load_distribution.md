# CockroachDB SQL Load Distribution Problem

## Summary

The CockroachDB cluster has 3 live nodes, but all SQL traffic is routed through a single node. The other two nodes hold replicated data but receive zero queries.

## Cluster State

| Node | Host | Selects (cumulative) | Inserts (cumulative) | Status |
|------|------|---------------------|---------------------|--------|
| 1 | anjuna2.dashlab.in:26257 | 0 | 0 | live, replicated only |
| 2 | colva3.dashlab.in:26257 | 33,236,395 | 227,916 | **all traffic** |
| 3 | colva2.dashlab.in:26257 | 0 | 0 | live, replicated only |

As of 2026-08-29.

## Root Cause

`scheduler/scheduler/settings.py` hardcodes the DB host as `colva3.dashlab.in:26257`. Every Django ORM query from every scheduler instance (utorda1, utorda2) connects through this single endpoint. CockroachDB distributes data internally via Raft replication, but the SQL session load is entirely on colva3.

### Current settings.py configuration

```python
# scheduler/scheduler/settings.py (lines 122–136)
DATABASES = {
    "default": {
        "ENGINE": "scheduler.db.cockroach",
        "NAME": "peercompute",
        "USER": "root",
        "PASSWORD": "",
        "HOST": "colva3.dashlab.in",   # colva2 down 2026-07-30; failover to colva3
        "PORT": "26257",
        "OPTIONS": {
            "sslmode": "verify-full",
            "sslrootcert": os.environ.get("DB_SSLROOTCERT", "/etc/cockroach/certs/ca.crt"),
            "sslcert": os.environ.get("DB_SSLCERT", "/etc/cockroach/certs/client.root.crt"),
            "sslkey": os.environ.get("DB_SSLKEY", "/etc/cockroach/certs/client.root.key"),
        },
        "CONN_MAX_AGE": 600,
    }
}
```

The `HOST` was changed from `colva2` to `colva3` on 2026-07-30 when colva2 went down. colva2 has since rejoined the cluster (node 3, live since Aug 5) but the connection string was never updated back. The comment in the code is now stale — colva2 is up.

## Why This Matters

- **Disk pressure on colva3 blocks the whole cluster.** Index backfills, bulk writes, and heavy query load all hit one machine. When colva3's disk drops below 5% free, CockroachDB pauses schema change jobs cluster-wide.
- **No query-level load distribution.** Even though anjuna2 and colva2 hold range replicas, they contribute nothing to query throughput. The cluster's 3x hardware is effectively doing 1x SQL work.
- **Single point of failure for the application.** If colva3 goes down, the application loses its DB connection entirely despite two other live nodes being available — unless the connection string is manually updated.

## What CockroachDB Does vs. Doesn't Do Automatically

CockroachDB does distribute data (Raft replication) and can internally route leaseholder reads to other nodes for ranges not leased on colva3. However, it does **not** automatically balance incoming SQL *connections* across nodes — that requires the client to connect to a different node or a load balancer in front of all three.

## Fix Options

### Option 1: Connection-level load balancer (recommended)
Run HAProxy or the CockroachDB-provided `cockroach gen haproxy` config in front of all three nodes. Point `settings.py` at the LB. This spreads SQL sessions across all nodes.

```
# Generate haproxy config
cockroach gen haproxy --certs-dir=/etc/cockroach/certs --host=colva3.dashlab.in:26257
```

### Option 2: Split connection strings per scheduler
Point utorda1 at `anjuna2.dashlab.in:26257` and utorda2 at `colva2.dashlab.in:26257` via their `.env` files. Simpler but manual — still a SPOF per scheduler.

### Option 3: Use CockroachDB connection string with multiple hosts
Psycopg3 / Django supports multi-host connection strings:
```
postgresql://user@colva3.dashlab.in:26257,anjuna2.dashlab.in:26257,colva2.dashlab.in:26257/peercompute
```
Django's `HOST` field does not support this directly, but it can be passed via `OPTIONS -> dsn`.

## Immediate Workaround

No action needed right now — the cluster is functional. But before the next experiment, check colva3 disk free space:

```bash
ssh peercompute@colva3.dashlab.in "df -h /dev/sda1"
```

If below 10% free, clear space or the next bulk index backfill or write-heavy experiment run may pause again.
