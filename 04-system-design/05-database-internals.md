# Database Internals for Backend Engineers

## Problem

Your movie booking system occasionally gets "Serialization conflict" errors. When you investigate, 5% of concurrent bookings fail with ROLLBACK. You suspect seat selection is the issue, but EXPLAIN doesn't show obvious problems. You have a 100M-row booking table that consumes 500GB, despite only 10M active bookings. Your backup takes 8 hours. A single analytics query locks the table for minutes. Query performance degraded 20% last month for no apparent reason.

Understanding database internals transforms you from someone who writes `SELECT *` to someone who designs for concurrent correctness, scales to billions of rows, and diagnoses performance anomalies. This lesson covers PostgreSQL's storage engine, indexing, locking, and optimization.

## Theory

### Storage Engines: B-tree vs LSM-tree

**B-tree** (PostgreSQL, MySQL InnoDB):
- Optimized for reads and point lookups
- Balanced tree structure: O(log N) search
- Every value stored once (no duplication across levels)
- Writes go to WAL first, then applied to tree (ordered writes to disk)
- Good for OLTP (Online Transaction Processing): many small reads/writes

**LSM-tree** (RocksDB, Cassandra, HBase):
- Optimized for writes
- Data written to in-memory buffer (memtable), flushed to disk in sorted runs (sstables)
- Multiple copies of same key across levels (compaction merges them)
- Reads must check multiple levels (slower random reads)
- Good for write-heavy workloads and sequential reads

PostgreSQL uses B-tree internally. For a movie booking system with high write volume and strong consistency needs, B-tree is correct.

### PostgreSQL Storage: Pages, Tuples, TOAST, Heap

PostgreSQL organizes tables into **pages** (8KB by default). Each page holds multiple rows (**tuples**). A table is just a file of sequential pages.

Each tuple has:
- **Header**: transaction info (xmin, xmax), hint bits
- **NULL bitmap**: which columns are NULL
- **Data**: actual column values

If a value is > 2KB (like a large JSON field), PostgreSQL stores it in TOAST (The Oversized Attribute Storage Technique): the main tuple has a pointer, data stored separately. This keeps tuple size manageable.

When you `INSERT`, PostgreSQL:
1. Finds a page with free space
2. Appends tuple to page
3. Updates page header and indexes
4. Writes WAL entry (can commit immediately)

When you `UPDATE`, PostgreSQL doesn't modify in-place. Instead:
1. Marks old tuple as deleted (xmax = current xid)
2. Inserts new tuple with xmin = current xid
3. Older transactions still see old tuple (MVCC)
4. Eventually VACUUM removes dead tuples

This MVCC design enables reads without blocking writes, but creates **table bloat**: old tuples accumulate. A table with 10M rows might have 20M physical tuples after updates, wasting 50% of disk.

### Indexing Deep Dive

**B-tree index** is the default:
```
                [50]
              /      \
           [25]      [75]
          /  \       /  \
        [10][40]  [60][90]
        / \  / \  / \  / \
       5  15 35 45 55 65 85 95
```

Each internal node stores keys and pointers. Leaf nodes store keys and row pointers (TID = page:offset). Lookup for value 85: start at root, follow right pointer, left pointer, find leaf, return TID.

For movie bookings, index on `(movie_id, is_available)` is faster than table scan:

```
INDEX booking_movie_availability
├─ movie_id=1, is_available=true
│  ├─ is_available=true → [TID1, TID2, TID3, ...]
│  └─ is_available=false → [TID4, TID5, ...]
├─ movie_id=2, ...
```

When you query `SELECT COUNT(*) FROM seats WHERE movie_id=1 AND is_available=true`, PostgreSQL can answer from the index alone (index-only scan), never touching the heap.

**Hash index**: instant O(1) lookup but only equality (`=`), not range (`>`). Also, hash indexes aren't replicated (not recommended).

**GIN (Generalized Inverted Index)**: for JSON and arrays. A GIN index on `movie->>'genre'` lets PostgreSQL quickly find all rows where genre is "Action."

**GiST (Generalized Search Tree)**: for spatial data (PostGIS). Allows range queries, nearest-neighbor searches.

**BRIN (Block Range Index)**: for time-series data. Stores min/max value for each block. Tiny index, great for `WHERE created_at > NOW() - INTERVAL 7 days`.

**Covering indexes** (`INCLUDE` clause): add non-indexed columns to leaf nodes for index-only scans.

```sql
CREATE INDEX idx_booking_dates ON bookings(created_at) INCLUDE (user_id, movie_id);
```

Now `SELECT user_id, movie_id FROM bookings WHERE created_at > '2025-01-01'` reads only index, never heap.

**Partial indexes**: index only rows matching a condition.

```sql
CREATE INDEX idx_active_bookings ON bookings(user_id) WHERE status = 'CONFIRMED';
```

Saves space and speeds up queries on active rows. Scan of active bookings doesn't waste CPU on inactive.

**Expression indexes**: index computed values.

```sql
CREATE INDEX idx_user_name_lower ON users(LOWER(name));
-- Enables: SELECT * FROM users WHERE LOWER(name) = 'alice';
```

### EXPLAIN ANALYZE: Reading Query Plans

```sql
EXPLAIN ANALYZE
SELECT user_id, COUNT(*) as bookings
FROM bookings
WHERE movie_id = 1 AND created_at > NOW() - INTERVAL '30 days'
GROUP BY user_id;
```

Output:
```
Gather Aggregate  (cost=1000.00..2000.00 rows=100 width=16)
  Workers Launched: 2
  -> Partial Aggregate  (cost=0.42..0.43 rows=1 width=16)
    -> Parallel Seq Scan on bookings  (cost=0.00..10000.00 rows=500000 width=12)
          Filter: ((movie_id = 1) AND (created_at > now() - '30 days'::interval))
          Rows: 500000  Loops: 1
          Actual Time: 0.012..450.123 rows=500000
```

**Seq Scan** is the enemy. It reads every page of the table—expensive for large tables.

**Index Scan** is better. If there's an index on `movie_id`, PostgreSQL uses it:

```
Index Scan using idx_movie on bookings  (cost=0.42..500.00 rows=50000 width=12)
  Index Cond: (movie_id = 1)
  Filter: (created_at > now() - '30 days'::interval)
```

It uses the index to find rows where `movie_id=1`, then applies the time filter.

**Nested Loop Join**: joins two tables by looping. For each row in left table, scan right table. O(N*M). Slow for large joins.

**Hash Join**: load smaller table into hash table, scan larger table and probe. O(N+M). Better for joins.

**Sort Merge Join**: both tables sorted, merge pointers. O(N log N + M log M). Good when tables already sorted.

Red flags:
- `Seq Scan on large table` with `cost=0.00` (estimated 0 rows) but `Rows: 500000` (actual 500K). Planner is wrong. Update table statistics: `ANALYZE bookings;`
- `Nested Loop` on join of 1M + 1M rows. Change join order or add index.
- `Sort on large dataset`. Might need `work_mem` increase or better index.

### MVCC: Transaction Isolation

Every tuple has:
- `xmin`: transaction ID that inserted this tuple
- `xmax`: transaction ID that deleted this tuple (if deleted)

When transaction T1 reads, PostgreSQL shows only tuples where:
- `xmin` is committed and <= T1's ID (was inserted before T1)
- `xmax` is null or > T1's ID (was not deleted before T1)

This allows **READ COMMITTED**: transaction sees committed changes, not in-flight.

**REPEATABLE READ**: transaction captures a snapshot at start. All reads see that snapshot, even if other transactions commit. Good for reporting queries (consistent view of data).

**SERIALIZABLE**: no anomalies. If two transactions conflict, one aborts. Implemented via Serializable Snapshot Isolation (SSI) in PostgreSQL.

For movie booking, SERIALIZABLE prevents overselling:

```go
// T1 and T2 both try to book the last seat
tx1, _ := db.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.Serializable})
tx2, _ := db.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.Serializable})

// T1: SELECT COUNT(*) FROM seats WHERE available=true -> 1 seat
// T2: SELECT COUNT(*) FROM seats WHERE available=true -> 1 seat (hasn't seen T1's UPDATE yet)

// T1: UPDATE seats SET available=false WHERE ...
// T1: COMMIT ✓

// T2: UPDATE seats SET available=false WHERE ... (same seat!)
// T2: COMMIT ✗ SERIALIZATION CONFLICT
```

T2 aborts. Must retry.

### Write-Ahead Log (WAL)

Before modifying a page, PostgreSQL writes the operation to WAL. The WAL entry describes the change (e.g., "set column X to value Y at offset Z"). Only after WAL is synced to disk is the change applied to the actual page.

If crash happens:
1. Recover WAL from disk
2. Replay all operations in order
3. Data is consistent

This is why `fsync=on` is critical in PostgreSQL. It guarantees WAL is actually on disk, not in OS buffer. `fsync=off` is 10x faster but risks data loss.

WAL also enables **replication**: standby reads WAL from primary, applies same operations. Both databases stay in sync.

WAL also enables **logical decoding**: extract structured changes (who inserted/updated/deleted what) for event streaming, CDC (Change Data Capture).

### Vacuum: Dead Tuple Cleanup

After UPDATE/DELETE, old tuples remain. `VACUUM` scans the table and marks free space. `VACUUM FULL` rewrites the entire table (locks it). `AUTOVACUUM` runs periodically.

Without vacuum, table bloats:
```
Initial: 100K rows = 100MB
After updates: 200K tuples = 200MB (100K live, 100K dead)
After VACUUM: 100K tuples, 100MB free space (but still 200MB file)
After VACUUM FULL: 100MB file (compact)
```

Table bloat harms performance: more pages to read for same data, more memory for same working set. Check bloat:

```sql
SELECT current_database(), schemaname, tablename, ROUND(100 * pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename))::numeric / pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename))::numeric, 2) as bloat_ratio FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema');
```

Tune autovacuum for high-churn tables:

```sql
ALTER TABLE bookings SET (
  autovacuum_vacuum_scale_factor = 0.01, -- vacuum at 1% bloat (default 10%)
  autovacuum_analyze_scale_factor = 0.005
);
```

### Connection Management: pgBouncer

PostgreSQL has a process-per-connection model: each connection spawns a backend process (RAM overhead). 1000 connections = 1000 processes = large memory footprint.

pgBouncer is a connection pool. Clients connect to pgBouncer, pgBouncer reuses a smaller pool of connections to the database:

```
1000 client connections → pgBouncer → 20 database connections
```

Two modes:

**Session mode**: each client gets a dedicated connection from pool. When client disconnects, connection returns to pool. More overhead but preserves prepared statements, transactions per connection.

**Transaction mode**: each transaction gets a connection. After COMMIT, connection returns. Saves resources but breaks `SET SESSION` variables and multi-statement transactions.

For booking API, transaction mode is fine:

```
pgBouncer config:
pool_mode = transaction
max_client_conn = 5000
default_pool_size = 50
```

Without pooling, 5000 concurrent connections = 5000 backends = 5GB+ memory. With pooling, 50 database connections = minimal memory.

### Lock Management

PostgreSQL has fine-grained locking:

- **Row-level lock**: `SELECT ... FOR UPDATE` locks specific rows, other transactions can read/modify other rows.
- **Table-level lock**: `LOCK TABLE` locks entire table, useful for DDL.
- **Advisory locks**: application-defined locks via functions like `pg_advisory_lock(id)`. Useful for custom critical sections (e.g., only one process should vacuum a table at a time).

Deadlock example:

```
T1: LOCK table A, then table B
T2: LOCK table B, then table A
-- Both wait for each other → DEADLOCK
```

PostgreSQL detects deadlocks and aborts one transaction.

For movie booking, advisory locks prevent overselling:

```go
// Only one transaction can hold lock for user 42
tx.QueryRow(ctx, "SELECT pg_advisory_lock($1)", userID).Scan()
defer tx.QueryRow(ctx, "SELECT pg_advisory_unlock($1)", userID).Scan()

// Now safely book without race condition
```

### Query Optimization: Common Antipatterns

**N+1 problem**:
```go
// WRONG: 1 query to fetch users, N queries to fetch bookings
users := fetchAllUsers() // 1 query
for user := range users {
  user.Bookings = fetchUserBookings(user.ID) // N queries
}

// RIGHT: 1 query with JOIN
SELECT u.*, b.* FROM users u LEFT JOIN bookings b ON u.id = b.user_id;
```

**SELECT ***: retrieves all columns, even unneeded. Wastes bandwidth, memory, cache.

```sql
-- WRONG
SELECT * FROM bookings WHERE user_id = 1; -- gets all columns

-- RIGHT
SELECT id, created_at, movie_id FROM bookings WHERE user_id = 1;
```

**Missing indexes**: sequential scan instead of index scan.

```sql
-- WRONG: no index, full table scan
SELECT * FROM bookings WHERE status = 'CANCELLED';

-- RIGHT
CREATE INDEX idx_status ON bookings(status);
```

**CTE materialization**: CTEs are sometimes materialized (computed fully before use), defeating optimization.

```sql
-- MIGHT materialize, defeating join optimization
WITH active_bookings AS (
  SELECT * FROM bookings WHERE status = 'CONFIRMED'
)
SELECT * FROM active_bookings WHERE movie_id = 1;

-- BETTER: use JOIN or subquery
SELECT * FROM bookings WHERE status = 'CONFIRMED' AND movie_id = 1;
```

Use `EXPLAIN ANALYZE` to check if CTE is materialized. If unnecessary, inline it.

### Partitioning

For very large tables (billions of rows), partition by range, list, or hash:

```sql
-- Partition by date range
CREATE TABLE bookings (
  id BIGSERIAL, user_id BIGINT, movie_id BIGINT, created_at TIMESTAMP
) PARTITION BY RANGE (created_at);

CREATE TABLE bookings_2025_q1 PARTITION OF bookings
  FOR VALUES FROM ('2025-01-01') TO ('2025-04-01');
CREATE TABLE bookings_2025_q2 PARTITION OF bookings
  FOR VALUES FROM ('2025-04-01') TO ('2025-07-01');
```

Benefits:
- **Partition pruning**: query for Q1 data only touches Q1 partition, not entire table
- **Easier maintenance**: VACUUM one partition instead of entire 1TB table
- **Parallel queries**: scan multiple partitions in parallel
- **Drop old data**: drop entire partition (instant) instead of DELETE (slow)

Tradeoff: more complex schema, planner must work harder.

## Production Code

### Optimized Movie Booking with Concurrent Safety

```go
package main

import (
	"context"
	"fmt"
	"log"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type BookingDB struct {
	pool *pgxpool.Pool
}

// BookSeatWithSerializableIsolation books a seat with SERIALIZABLE isolation.
// Prevents overselling even with concurrent bookings.
func (b *BookingDB) BookSeatWithSerializableIsolation(ctx context.Context, userID, movieID int64, seatCount int32) (bookingID int64, err error) {
	tx, err := b.pool.BeginTx(ctx, pgx.TxOptions{
		IsoLevel: pgx.Serializable,
	})
	if err != nil {
		return 0, fmt.Errorf("begin tx: %w", err)
	}
	defer tx.Rollback(ctx)

	// Check availability within transaction
	var available int32
	err = tx.QueryRow(ctx, `
		SELECT COALESCE(COUNT(*), 0)
		FROM seats
		WHERE movie_id = $1 AND is_available = true
		AND seat_id NOT IN (
			SELECT seat_id FROM seat_reservations
			WHERE booking_id IN (
				SELECT id FROM bookings
				WHERE movie_id = $1 AND status = 'CONFIRMED'
			)
		)
	`, movieID).Scan(&available)
	if err != nil {
		return 0, fmt.Errorf("check availability: %w", err)
	}

	if available < seatCount {
		return 0, fmt.Errorf("only %d seats available, need %d", available, seatCount)
	}

	// Create booking
	err = tx.QueryRow(ctx, `
		INSERT INTO bookings (user_id, movie_id, status, created_at)
		VALUES ($1, $2, 'CONFIRMED', NOW())
		RETURNING id
	`, userID, movieID).Scan(&bookingID)
	if err != nil {
		return 0, fmt.Errorf("insert booking: %w", err)
	}

	// Reserve seats (in order to avoid deadlocks, lock by seat_id)
	rows, err := tx.Query(ctx, `
		SELECT id FROM seats
		WHERE movie_id = $1 AND is_available = true
		ORDER BY id
		LIMIT $2
		FOR UPDATE
	`, movieID, seatCount)
	if err != nil {
		return 0, fmt.Errorf("lock seats: %w", err)
	}
	defer rows.Close()

	var seatIDs []int64
	for rows.Next() {
		var seatID int64
		if err := rows.Scan(&seatID); err != nil {
			return 0, err
		}
		seatIDs = append(seatIDs, seatID)
	}

	if len(seatIDs) < int(seatCount) {
		return 0, fmt.Errorf("race condition: fewer seats locked than expected")
	}

	// Mark seats as booked
	_, err = tx.Exec(ctx, `
		UPDATE seats SET is_available = false
		WHERE id = ANY($1)
	`, seatIDs)
	if err != nil {
		return 0, fmt.Errorf("update seats: %w", err)
	}

	// Insert seat reservations (audit trail)
	batch := &pgx.Batch{}
	for _, seatID := range seatIDs {
		batch.Queue(`
			INSERT INTO seat_reservations (booking_id, seat_id, reserved_at)
			VALUES ($1, $2, NOW())
		`, bookingID, seatID)
	}
	results := tx.SendBatch(ctx, batch)
	_, err = results.Exec()
	results.Close()
	if err != nil {
		return 0, fmt.Errorf("insert reservations: %w", err)
	}

	err = tx.Commit(ctx)
	if err != nil {
		// Check if serialization conflict
		if pgx.ErrorCode(err) == "40001" { // SERIALIZATION_FAILURE
			return 0, fmt.Errorf("serialization conflict, retry: %w", err)
		}
		return 0, fmt.Errorf("commit: %w", err)
	}

	return bookingID, nil
}

// OptimizedAvailabilityCheck uses covering index for index-only scan.
// Fast for checking availability without touching heap.
func (b *BookingDB) OptimizedAvailabilityCheck(ctx context.Context, movieID int64) (available int32, err error) {
	// Assumes index: CREATE INDEX idx_movie_availability
	// ON seats(movie_id, is_available) INCLUDE (seat_id);
	// This allows index-only scan.

	err = b.pool.QueryRow(ctx, `
		SELECT COUNT(*)
		FROM seats
		WHERE movie_id = $1 AND is_available = true
	`, movieID).Scan(&available)

	return
}

// CheckTableBloat returns bloat estimate for a table.
func (b *BookingDB) CheckTableBloat(ctx context.Context, tableName string) (bloatPercent float64, liveRows int64, deadRows int64, err error) {
	err = b.pool.QueryRow(ctx, `
		SELECT
			(dead_tuples::float / NULLIF(live_tuples + dead_tuples, 0) * 100) as bloat_percent,
			live_tuples,
			dead_tuples
		FROM pg_stat_user_tables
		WHERE relname = $1
	`, tableName).Scan(&bloatPercent, &liveRows, &deadRows)

	return
}

// AnalyzeTable updates table statistics for query planner.
func (b *BookingDB) AnalyzeTable(ctx context.Context, tableName string) error {
	_, err := b.pool.Exec(ctx, fmt.Sprintf("ANALYZE %s", tableName))
	return err
}

// VacuumTable removes dead tuples and defragments.
func (b *BookingDB) VacuumTable(ctx context.Context, tableName string) error {
	_, err := b.pool.Exec(ctx, fmt.Sprintf("VACUUM %s", tableName))
	return err
}

// OptimizedConcurrentBooking uses advisory lock to serialize per-user bookings.
// Simpler than SERIALIZABLE, avoids retries.
func (b *BookingDB) OptimizedConcurrentBooking(ctx context.Context, userID, movieID int64, seatCount int32) (bookingID int64, err error) {
	// Acquire advisory lock for user to serialize their bookings
	var lockID int64 = userID % 1000000 // Keep ID range manageable
	err = b.pool.QueryRow(ctx, "SELECT pg_advisory_lock($1)", lockID).Scan()
	if err != nil {
		return 0, fmt.Errorf("lock: %w", err)
	}
	defer b.pool.QueryRow(ctx, "SELECT pg_advisory_unlock($1)", lockID).Scan()

	// Now safe to check and book without serialization conflicts
	tx, _ := b.pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.ReadCommitted})
	defer tx.Rollback(ctx)

	// ... rest of booking logic (same as above)

	return bookingID, tx.Commit(ctx)
}

func main() {
	ctx := context.Background()

	pool, err := pgxpool.New(ctx, "postgres://user:pass@localhost/bookings")
	if err != nil {
		log.Fatal(err)
	}
	defer pool.Close()

	db := &BookingDB{pool: pool}

	// Try to book 2 seats
	bookingID, err := db.BookSeatWithSerializableIsolation(ctx, 42, 1, 2)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Printf("Booked: %d\n", bookingID)

	// Check table bloat
	bloat, live, dead, _ := db.CheckTableBloat(ctx, "bookings")
	fmt.Printf("Bloat: %.1f%% (live: %d, dead: %d)\n", bloat, live, dead)

	// If bloated, vacuum
	if bloat > 20 {
		db.VacuumTable(ctx, "bookings")
	}
}
```

### Schema with Proper Indexes and Partitioning

```sql
-- Bookings table partitioned by month
CREATE TABLE bookings (
    id BIGSERIAL,
    user_id BIGINT NOT NULL,
    movie_id BIGINT NOT NULL,
    seat_count INT NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- Create partitions for recent months
CREATE TABLE bookings_2025_01 PARTITION OF bookings
    FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
CREATE TABLE bookings_2025_02 PARTITION OF bookings
    FOR VALUES FROM ('2025-02-01') TO ('2025-03-01');
CREATE TABLE bookings_2025_03 PARTITION OF bookings
    FOR VALUES FROM ('2025-03-01') TO ('2025-04-01');

-- Indexes for query patterns
CREATE INDEX idx_booking_user ON bookings(user_id)
    INCLUDE (movie_id, status, created_at);

CREATE INDEX idx_booking_movie ON bookings(movie_id, status)
    INCLUDE (user_id, created_at);

CREATE INDEX idx_booking_status ON bookings(status)
    WHERE status = 'CONFIRMED'; -- Partial index for active bookings

-- Seats table with advisory lock support
CREATE TABLE seats (
    id BIGSERIAL PRIMARY KEY,
    movie_id BIGINT NOT NULL,
    seat_number INT NOT NULL,
    is_available BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL
);

CREATE INDEX idx_movie_availability ON seats(movie_id, is_available)
    INCLUDE (seat_number); -- Covering index for index-only scan

-- Seat reservations (audit trail)
CREATE TABLE seat_reservations (
    booking_id BIGINT NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    seat_id BIGINT NOT NULL REFERENCES seats(id) ON DELETE CASCADE,
    reserved_at TIMESTAMP NOT NULL,
    PRIMARY KEY (booking_id, seat_id)
);

-- Autovacuum tuning for high-churn bookings table
ALTER TABLE bookings SET (
    autovacuum_vacuum_scale_factor = 0.01,
    autovacuum_analyze_scale_factor = 0.005,
    autovacuum_vacuum_cost_delay = 2,
    autovacuum_vacuum_cost_limit = 1000
);
```

## Tradeoffs and What Breaks

### Long-Running Transactions

A transaction that holds locks for minutes blocks other transactions. MVCC doesn't help if you're holding locks. Solution: keep transactions short. Load data in app memory, process, then commit. Don't do work inside transactions.

### Bloated Tables

Table grows to 500GB because of dead tuples. `VACUUM FULL` locks table for hours. Solution: regular VACUUM (can run online), or partition by time and drop old partitions.

### Index Bloat

Indexes also bloat. `REINDEX` rebuilds index but locks table. Solution: monitor `pg_stat_user_indexes.idx_blks_hit` vs `pg_stat_user_indexes.idx_blks_read`. If ratio is low, index is ineffective. Rebuild with `REINDEX CONCURRENTLY`.

### Connection Exhaustion

Pool of 50 connections, 5000 waiting clients. Some will timeout. Solution: use transaction pooler (pgBouncer) or reduce connection hold time.

### Lock Contention

Advisory lock on `user_id % 1000000` means 1M concurrent users map to 1000 locks. If many users book simultaneously, they contend on same lock. Solution: increase lock namespace or use SERIALIZABLE isolation instead.

## Interview Corner

**Q1: You have a bookings table with 1B rows. Queries are slow. How do you debug?**

A: First, check table size: `SELECT pg_size_pretty(pg_total_relation_size('bookings'));` If it's 100GB for 1B rows (100B per row average), that's fine. If it's 500GB, table is bloated.

Check bloat: Use the pgstattuple extension (or query pg_stat_user_tables for live_tuples vs dead_tuples). If bloat > 20%, vacuum.

Then, run EXPLAIN ANALYZE on slow query:
```sql
EXPLAIN ANALYZE
SELECT * FROM bookings WHERE movie_id = 1 AND created_at > NOW() - INTERVAL '30 days';
```
Check for Seq Scan (full table scan, bad) vs Index Scan (using index, good). If Seq Scan but an index exists, the planner thinks seq scan is faster (maybe stats are old).

Update statistics: `ANALYZE bookings;` and retry.

Check query plan: are you using the right join strategy? Is the planner picking nested loop instead of hash join for large joins? Use `EXPLAIN (ANALYZE, BUFFERS)` to see actual I/O.

Finally, check partition strategy. If query filters by date, partition by month and use partition pruning to exclude partitions.

**Q2: SERIALIZABLE isolation causes 20% of bookings to fail with serialization conflict. How do you fix?**

A: Options:
1. Retry failed transactions (with exponential backoff). Conflict means two users booked same seat; retry will catch it.
2. Switch to advisory locks (simpler, no retries, but coarser granularity).
3. Use application-level queuing: all booking requests go to a queue, processed sequentially. No conflicts, but latency increases.

For booking system, option 1 (retry) is standard. Add exponential backoff and limit retries to 3.

**Q3: Covering indexes, partial indexes, expression indexes—when do you use each?**

A:
- **Covering**: when you query a subset of columns. E.g., `SELECT user_id, movie_id FROM bookings WHERE created_at > X` can use index-only scan with INCLUDE.
- **Partial**: when you filter by a common condition. E.g., `WHERE status = 'CONFIRMED'` appears in 80% of queries, so index only active rows.
- **Expression**: when query filters by computed value. E.g., `WHERE LOWER(email) = 'alice@example.com'` needs expression index on `LOWER(email)`.

Measure impact with EXPLAIN ANALYZE.

**Q4: Partition by date or by hash?**

A:
- **By date**: good for time-series data (bookings). Oldest partitions can be dropped (instant). Queries filtering by date prune partitions.
- **By hash**: distributes rows evenly. Good for range partitioning isn't possible (e.g., user_id). Can't drop old data as easily.

For booking, partition by `created_at` (month). Quarterly rotation: drop old quarters, create new.

**Q5: How do you detect and prevent N+1 queries in production?**

A: Options:
1. Middleware that logs all database queries and counts per HTTP request. If count > threshold, alert.
2. OpenTelemetry spans: each query is a span. Bursts of spans for one request show N+1.
3. Use ORMs (GORM, sqlc) that can detect N+1 (some have heuristics).

Best: use spans + logs correlation. See all queries for a request, count them. Set a budget: "a GET request should make <= 5 database queries." Exceed that, investigate.

**Q6: Advisory locks vs SERIALIZABLE isolation: when do you use each?**

A: **SERIALIZABLE isolation** detects conflicts at transaction level. If two transactions try to book same seat, one aborts with serialization conflict. You retry in app (exponential backoff). Pros: strict correctness, automatic conflict detection. Cons: retries add latency, failure rate increases under contention.

**Advisory locks** are explicit mutual exclusion. You acquire lock before transaction, commit releases it. Pros: predictable, no retries, simple. Cons: coarser granularity (lock all user bookings, not just one seat), requires manual management (risk of deadlock if not ordered correctly).

Choose: for seat selection (high contention), advisory locks are simpler. For general data integrity (low conflict rate), SERIALIZABLE is better (less boilerplate).

**Q7: How do you handle connection pool exhaustion in production?**

A: Pool exhaustion: all connections borrowed, new requests wait. If timeout > 5s, customer sees error.

Prevention:
1. Set realistic pool size: 20-50 connections typical, depends on app. For booking API with 100 req/s and 50ms avg query time = 5 concurrent queries = need 10+ pool connections. Add buffer (20-30).
2. Monitor pool: active connections, wait queue depth. Alert if queue > 10.
3. Use connection timeout: if can't get connection in 5s, fail fast instead of hanging.
4. Use transaction pooler (pgBouncer): reuse connections across requests. Reduces backend process count.
5. Reduce transaction time: don't do work inside transactions. Load data in app, process, then commit.

If exhausted in production:
1. Increase pool size (if database can handle more connections)
2. Add pgBouncer (quick win, 3-5x capacity increase)
3. Identify slow queries blocking connections

## Advanced Query Optimization Techniques

### Query Plan Caching and Prepared Statements

PostgreSQL caches query plans. When you execute a query, planner generates a plan (expensive). Cached plans are reused.

```go
// WITHOUT prepared statement: plan generated every time
rows, _ := db.Query("SELECT * FROM bookings WHERE user_id = $1", userID)

// WITH prepared statement: plan cached
stmt, _ := db.Prepare("SELECT * FROM bookings WHERE user_id = $1")
defer stmt.Close()
rows1, _ := stmt.Query(userID)
rows2, _ := stmt.Query(userID) // Reuses cached plan
```

pgx handles this transparently. Always use parameters (parameterized queries), never string concatenation. pgx caches plans automatically.

### Join Optimization Techniques

When joining large tables, join order matters:

```sql
-- SLOW: join large table first, then filter
SELECT b.*, m.title
FROM bookings b
JOIN movies m ON b.movie_id = m.id
WHERE b.movie_id = 1; -- Filter applied AFTER join of all rows

-- FAST: filter before join
SELECT b.*, m.title
FROM bookings b
WHERE b.movie_id = 1  -- Filter reduces rows before join
JOIN movies m ON b.movie_id = m.id;
```

PostgreSQL usually optimizes this automatically (filters pushed down), but complex queries might not. Use `EXPLAIN ANALYZE` to check.

### Aggregation with GROUP BY

For movie ratings, computing average rating over 1M rows is expensive. Precompute and cache:

```sql
-- Compute once, cache result
CREATE MATERIALIZED VIEW movie_ratings AS
SELECT movie_id, AVG(rating) as avg_rating, COUNT(*) as review_count
FROM reviews
GROUP BY movie_id;

-- Query is instant: O(1)
SELECT * FROM movie_ratings WHERE movie_id = 1;

-- Refresh periodically (expensive) or on-demand
REFRESH MATERIALIZED VIEW movie_ratings;
```

Tradeoff: 1-minute staleness (view updated hourly) vs always-fresh aggregations.

## Exercise

Build a multi-tenant booking system with optimized queries:

1. Create `tenants` table (each tenant is a different movie theater chain).
2. Create `movies` and `seats` tables (scoped per tenant).
3. Create `bookings` and `seat_reservations` tables.
4. Implement:
   - `BookSeat(tenantID, userID, movieID, seatCount)` with SERIALIZABLE isolation and advisory locks
   - `CheckAvailability(tenantID, movieID)` with index-only scan (covering index)
   - `GetUserBookings(tenantID, userID)` with efficient pagination (cursor-based, not offset)
   - `GetMovieAnalytics(tenantID, movieID)` with materialized view (aggregate ratings, review count)
5. Create indexes: covering, partial, composite, expression indexes for LOWER(name) searches
6. Partition bookings by month (range partitioning)
7. Measure with EXPLAIN ANALYZE and pgstattuple (bloat detection)
8. Profile with pg_stat_user_tables (hit ratio, bloat %)

Expected performance:
- P99 latency < 100ms for BookSeat (even with contention)
- < 10ms for CheckAvailability (index-only scan, no disk I/O)
- Cursor pagination maintains constant speed even for late pages (not offset-based)
- Analytics queries < 10ms (cached materialized view)
- Table bloat < 10% after 100K bookings (autovacuum working)

---

