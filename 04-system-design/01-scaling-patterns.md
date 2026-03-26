# Scaling Patterns: From 100 to 100M Users

## Table of Contents
1. [Horizontal vs Vertical Scaling](#horizontal-vs-vertical-scaling)
2. [Database Scaling Deep Dive](#database-scaling-deep-dive)
3. [Connection Pooling](#connection-pooling)
4. [Caching Strategies](#caching-strategies)
5. [Redis Deep Dive](#redis-deep-dive)
6. [CDN and Edge Caching](#cdn-and-edge-caching)
7. [Message Queues](#message-queues)
8. [Load Balancing](#load-balancing)
9. [Auto-scaling](#auto-scaling)
10. [Database Indexing](#database-indexing)
11. [Production Scenario: Movie Booking System](#production-scenario-movie-booking-system)
12. [What Breaks in Production](#what-breaks-in-production)
13. [Interview Questions](#interview-questions)

## Horizontal vs Vertical Scaling

Scaling is the ability to handle increasing load. It's often the most expensive investment in a backend system and should be approached strategically.

### Vertical Scaling (Scale Up)

Vertical scaling means increasing the capacity of a single machine: more CPU cores, more RAM, faster storage, better network interfaces.

**Characteristics:**
- Simple to implement: just buy bigger hardware
- Limited by physical constraints: a single machine has an upper bound
- No distributed systems complexity: single machine, single source of truth
- Cost grows non-linearly: server pricing curves favor mid-range machines
- Downtime required: typically need to migrate and restart

**When it's appropriate:**
- Starting out: Vertical scaling is fastest to market
- I/O bound services: if you need raw latency (low single-digit milliseconds), a beefy machine can deliver
- Stateful services: Redis, in-memory caches, session stores benefit from more RAM
- Under ~10,000 QPS: vertical scaling often makes financial sense
- Fixed workloads: predictable, non-growing systems

**Cost analysis:** A server with 2x the CPU and 2x the RAM doesn't cost 2x; typically it costs 1.5-1.7x. A $2,000 server might be $3,000 at double capacity. This means per-unit cost becomes more favorable at larger sizes. But hardware still hits physical limits: the largest single server will be ~100-200 cores, 2-4TB RAM.

### Horizontal Scaling (Scale Out)

Horizontal scaling means distributing load across multiple machines. Every component becomes distributed: databases, caches, queues, services.

**Characteristics:**
- Complex: introduces network calls, partial failures, consistency challenges
- Unlimited ceiling: scale to thousands of machines
- No downtime: add servers while running
- Better cost efficiency at massive scale: commodity hardware
- Operational overhead: monitoring, orchestration, debugging becomes harder

**When it's appropriate:**
- High volume systems: >10,000 QPS
- Geographic distribution: serving users globally
- Fault tolerance: redundancy matters
- Elastic workloads: traffic spikes

**Cost analysis:** At 100,000 QPS across a cluster, you're paying for networking, orchestration, persistence, and redundancy. Total cost can exceed a few powerful servers at lower volumes. But past ~500K QPS, horizontal scaling becomes mandatory and cost-effective.

### Hybrid Approach (The Real World)

Production systems use both:
- Start with vertical scaling (one beefy application server + managed database)
- Add horizontal scaling at the bottleneck (database is often first)
- Use read replicas + caching before full horizontal scaling of application layer
- Eventually: multiple application servers + distributed database + caching layer

**Example Cost Curves:**
```
Vertical only (single server):
  100 QPS:   $2,000/month
  1,000 QPS: $3,500/month (hitting limits)
  10,000 QPS: impossible

Horizontal (10 servers):
  100 QPS:   $25,000/month (over-provisioned)
  10,000 QPS: $25,000/month (efficient)
  100,000 QPS: $100,000/month (scales linearly)

Hybrid (vertical + read replicas + caching):
  100 QPS:    $2,000/month
  1,000 QPS:  $5,000/month (1 server + 1 replica + Redis)
  10,000 QPS: $15,000/month (2 servers + 3 replicas + larger Redis)
  100,000 QPS: $150,000/month (5 servers + 10 replicas + Redis cluster)
```

---

## Database Scaling Deep Dive

Databases are the hardest thing to scale. Data is stateful and ordered; compute is stateless and fungible.

### Read Replicas

A read replica is an exact copy of the primary database that lags slightly behind.

**Setup:**
```
Master (writes) → WAL (Write-Ahead Log) → Replica 1, Replica 2, Replica N (reads)
```

**Benefits:**
- Scale read throughput: unlimited read replicas theoretically
- Geographic distribution: place replicas near users
- Analytics/reporting: heavy queries on replicas don't impact production

**Limitations:**
- Replication lag: writes aren't immediately visible on replicas (typically milliseconds to seconds)
- Write bottleneck: all writes still go to one master
- Consistency complications: applications must handle eventual consistency
- Failover complexity: promoting a replica requires careful orchestration

**Example: Movie Booking System**

```
Primary DB (Mumbai): handles all booking writes
├── Read Replica (Mumbai): seat inventory reads
├── Read Replica (London): regional queries
└── Read Replica (Singapore): regional queries

Application logic:
- Write booking: → Primary
- Read seat availability: → Nearest replica (may see stale data)
- Read user's bookings: → Primary (needs latest state)
```

**Replication lag handling:**
```go
// Problematic pattern
booking := WriteBooking(userID, showID, seats)
available := ReadAvailableSeats(showID) // May not see booking we just made!
if available < len(seats) {
    // Race condition: might show oversold state
}

// Better pattern
booking := WriteBooking(userID, showID, seats)
// Read from primary immediately after write
available := ReadAvailableSeatsFromPrimary(showID)
```

### Sharding Strategies

When a single database can't handle the volume, split data across multiple database instances (shards). Each shard holds a subset of data.

**Hash Sharding:**
```
Shard Key = hash(user_id) % num_shards
user_id 100 → hash("100") % 4 = shard 2
user_id 101 → hash("101") % 4 = shard 1
```

Pros: uniform distribution, simple
Cons: rebalancing is expensive (rehashing all data), difficult cross-shard queries

**Range Sharding:**
```
Shard 1: user_id 1-1,000,000
Shard 2: user_id 1,000,001-2,000,000
Shard 3: user_id 2,000,001-3,000,000
```

Pros: easy to locate (binary search), clean ranges
Cons: uneven load (user_id=1 might be 10x more active), requires reshuffling as ranges grow

**Geographic Sharding:**
```
Shard India: users with country='IN'
Shard US: users with country='US'
Shard EU: users with country='EU'
```

Pros: locality (data near users), regulatory compliance (GDPR)
Cons: uneven size (US shard may be 50% of data), cross-region queries are expensive

**Geo-Hash Sharding (Movie Booking):**
```
Movie theater location → geohash → shard
Theater in Mumbai (28.6°N, 77.2°E) → geohash "ttnc" → Asia shard
Theater in NYC (40.7°N, -74.0°W) → geohash "dr5r" → Americas shard

Seat availability lookup is now single-shard, locality-aware
```

### Shard Key Selection (Critical!)

Choosing a bad shard key kills scaling. Rules:
1. **High cardinality**: keys that have many distinct values (user_id good, gender bad)
2. **Even distribution**: key values should hash uniformly
3. **Immutable**: don't change shard keys (resharding is expensive)
4. **Query-friendly**: your most common queries should be single-shard
5. **Growth-aware**: anticipate how key distribution evolves

**Bad shard key examples:**

```go
// BAD: by country (uneven distribution)
// India has 1.4B people, Luxembourg has 600K
hash(country) % 10 → Singapore shard gets 40% of traffic

// BAD: by created_at (time-based)
// All new users go to today's shard
// Old shards have no writes (can't rebalance)

// BAD: by email_domain
// Gmail users all go to one shard (high cardinality illusion)

// GOOD: by user_id (primary key)
// Random distribution, immutable, high cardinality

// GOOD: by movie_id (for movie booking system)
// Theater location doesn't matter for booking sharding
// Movies have high cardinality, even distribution
```

### Consistent Hashing (Dynamic Sharding)

When shards are added/removed, simple `hash(key) % N` breaks: all keys rehash!

Consistent hashing solves this: only ~1/N of keys rehash when adding a shard.

**Algorithm:**
```
1. Map shard IDs to points on a ring [0, 2^32)
2. Map keys to points on the same ring using hash(key)
3. A key belongs to the nearest shard (clockwise)
4. Add shard → affects only 1/N of keys
```

**Virtual nodes:** Use 150-200 virtual nodes per shard for better distribution.

**Movie Booking Example:**
```
Ring: 0 -------- 2^32 -------- 0

Initial: 3 shards
Shard1 @ 100,000: owns keys hashing to [67K, 100K)
Shard2 @ 200,000: owns keys hashing to [100K, 200K)
Shard3 @ 50,000: owns keys hashing to [200K, 67K) [wraps around]

Add Shard4 @ 150,000:
Only keys in [100K, 150K) need to migrate from Shard2 to Shard4
~25% of Shard2's data, not all data
```

---

## Connection Pooling

Every database query requires a TCP connection. Creating connections is expensive (~10ms per connection including TLS handshake, authentication).

### Application-Level Pooling (pgxpool)

```go
// pgxpool (Go PostgreSQL driver with built-in pooling)
config, _ := pgxpool.ParseConfig("postgresql://user:pass@localhost/db")
config.MaxConns = 100          // Max 100 concurrent connections
config.MinConns = 10           // Keep 10 idle
config.MaxConnLifetime = 5 * time.Minute // Recycle connections

pool, _ := pgxpool.NewWithConfig(context.Background(), config)

// Each query checks out a connection from the pool, uses it, returns it
row := pool.QueryRow(ctx, "SELECT id FROM users WHERE id=$1", userID)
```

**Pool sizing:** A rule of thumb: `pool_size = (num_cores * 2) + effective_spindle_count`

For modern systems with SSDs: `pool_size = num_cores * 3` to `num_cores * 5`

Too small: application waits for connections (throughput limited)
Too large: database has more open connections than it can handle (memory exhausted)

### pgBouncer (Connection Pooling Proxy)

When you have many application servers, each with its own pool, the database sees `num_servers * pool_size` connections. This can exceed database limits.

pgBouncer sits between application and database, multiplexing many client connections into fewer database connections.

```
App1 ─────┐
App2 ─────┤
App3 ─────┼→ pgBouncer (300 client connections)
App4 ─────┤      ↓ multiplexes to
App5 ─────┘      Database (50 connections)
```

**Three pool modes:**

1. **Session mode** (default): connection stays assigned to a client for session duration
   - Most compatible, slight overhead
   - Use when you have few app servers

2. **Transaction mode**: connection returned to pool after each transaction
   - Better resource utilization (fewer DB connections needed)
   - Incompatible with prepared statements across transactions
   - Use at scale with many app servers

3. **Statement mode**: connection returned after each statement
   - Maximum connection reuse
   - Most restrictions (no multi-statement transactions)
   - Use only if you know what you're doing

**Movie Booking configuration:**
```ini
; pgbouncer.ini
[databases]
bookingdb = host=primary-db.internal port=5432 user=app password=secret

[pgbouncer]
pool_mode = transaction         ; Movie booking is transaction-based
max_client_conn = 5000          ; Expected concurrent connections
default_pool_size = 20          ; Per database
reserve_pool_size = 5           ; Extra connections for overflow
reserve_pool_timeout = 10       ; 10 second wait before failing
```

### Connection Limits in Practice

**PostgreSQL limits:**
```
max_connections = 200                    ; Hard limit
max_prepared_transactions = 200          ; If using prepared statements
work_mem = '256MB'                      ; Per query
shared_buffers = '8GB'                  ; Cache layer
```

**Common issues:**
- All connections in use: `too many connections` error
- Connection leak: application doesn't close connections
- Idle in transaction: transaction starts, blocks, never commits

**Debugging:**

```sql
-- Current connections
SELECT datname, count(*) FROM pg_stat_activity GROUP BY datname;

-- Connections per user
SELECT usename, count(*) FROM pg_stat_activity GROUP BY usename;

-- Connections in 'idle in transaction' (BAD)
SELECT pid, usename, state, query FROM pg_stat_activity
WHERE state = 'idle in transaction';
```

---

## Caching Strategies

Caching is about trading space and freshness for latency and throughput.

### Cache-Aside (Lazy Load)

Client checks cache first. On miss, load from database and populate cache.

```go
func GetUser(ctx context.Context, userID string) (*User, error) {
    // Try cache
    if user, err := cache.Get(ctx, userID); err == nil {
        return user, nil
    }

    // Cache miss: load from database
    user, err := db.GetUser(ctx, userID)
    if err != nil {
        return nil, err
    }

    // Populate cache (ignore errors)
    cache.Set(ctx, userID, user, 1*time.Hour)
    return user, nil
}
```

**Pros:** Simple, doesn't load unnecessary data
**Cons:** Cold cache is slow, complex cache invalidation

**Cache stampede:** If a popular key expires with high concurrency, many requests hit database simultaneously.

Solution: Use locks or probabilistic early expiration (refresh before expiry).

```go
func GetUserWithStampedeProtection(ctx context.Context, userID string) (*User, error) {
    user, ttl, _ := cache.GetWithTTL(ctx, userID)

    if user != nil && ttl > 30*time.Second {
        return user, nil // Use cached value
    }

    // Key expired or expiring soon: fetch and refresh
    user, err := db.GetUser(ctx, userID)
    if err != nil {
        if user != nil {
            return user, nil // Return stale data on error
        }
        return nil, err
    }

    cache.Set(ctx, userID, user, 1*time.Hour)
    return user, nil
}
```

### Read-Through

Cache is responsible for loading data from the database.

```go
// Configured in Redis or caching library
cache.ReadThrough("user:"+userID,
    func() (*User, error) {
        return db.GetUser(userID)
    },
    1*time.Hour)
```

**Pros:** Consistent logic, cleaner application code
**Cons:** Higher latency on misses (cache does database lookup), less flexible

### Write-Through

On write, update cache and database together.

```go
func UpdateUser(ctx context.Context, user *User) error {
    // Write to database first
    if err := db.SaveUser(ctx, user); err != nil {
        return err
    }

    // Then update cache
    cache.Set(ctx, user.ID, user, 1*time.Hour)
    return nil
}
```

**Pros:** Cache always has latest data, consistent view
**Cons:** Writes are slower (dual write), cascade failures (if cache is down, writes fail)

### Write-Behind (Write-Back)

Write to cache immediately, asynchronously write to database.

```go
func UpdateUserAsync(ctx context.Context, user *User) error {
    // Write to cache immediately
    cache.Set(ctx, user.ID, user, 1*time.Hour)

    // Queue database write (asynchronously)
    queue.Enqueue("user_updates", user)

    return nil
}

// Background worker
func ProcessUserUpdates(queue MessageQueue, db Database) {
    for update := range queue.Subscribe("user_updates") {
        db.SaveUser(context.Background(), update.User)
    }
}
```

**Pros:** Extremely fast writes, can batch writes to database
**Cons:** Data loss if cache fails before write, complex consistency handling

**Movie Booking use case:**
```
After booking, write to cache immediately (lock is released)
Asynchronously persist to database
If database write fails, retry with exponential backoff
Eventual consistency is acceptable for booking history
```

### Cache Invalidation (The Hardest Problem)

Phil Karlton: "There are only two hard things in Computer Science: cache invalidation and naming things."

**Strategies:**

1. **TTL-based**: Keys expire after time
   - Simple, handles errors gracefully
   - Data might be stale

2. **Event-based**: Invalidate on data changes
   - Can be accurate
   - Complex to implement, easy to miss events

3. **Dependency tracking**: Track what depends on what
   - Precise invalidation
   - Overhead

**Movie Booking Example:**

```go
// When seat is locked
cache.Delete(ctx, "seats:"+showID)  // Invalidate availability
cache.Delete(ctx, "occupancy:"+theatreID)  // Invalidate theatre occupancy

// When booking completes
cache.Delete(ctx, "user_bookings:"+userID)  // User's booking list

// When booking cancelled
cache.Delete(ctx, "seats:"+showID)
cache.Delete(ctx, "user_bookings:"+userID)

// Better approach: use cache tags
cache.Set(ctx, "seats:"+showID, seats,
    time.Hour,
    tags="seats", "theatre:"+theatreID)

// Invalidate by tag when theatre closes
cache.InvalidateByTag(ctx, "theatre:"+theatreID)
```

---

## Redis Deep Dive

Redis is an in-memory data structure store. The standard caching and session store.

### Data Structures

**Strings:** Basic key-value
```
SET key "value"
GET key
APPEND key " world"
INCR counter              ; Atomic increment
```

**Hashes:** Maps within Redis
```
HSET user:123 name "John" email "john@example.com"
HGETALL user:123
HINCRBY user:123 score 10
```

**Lists:** Ordered sequences (queues, stacks)
```
LPUSH queue "task1"
LPUSH queue "task2"
RPOP queue              ; FIFO
```

**Sets:** Unordered, unique members
```
SADD tags:movie "action" "thriller" "2024"
SISMEMBER tags:movie "action"  ; Is "action" in set?
SINTER tags:movie1 tags:movie2 ; Intersection
```

**Sorted Sets:** Like sets, but ordered by score
```
ZADD leaderboard 100 "user1" 95 "user2" 110 "user3"
ZRANGE leaderboard 0 -1              ; All members
ZREVRANGE leaderboard 0 9 WITHSCORES ; Top 10 with scores
ZRANK leaderboard "user2"             ; Rank of user2
```

### Movie Booking Redis Usage

```go
// Seat locking (set with expiry)
SETEX "lock:show:123" 60 "user:456"
// Check if locked
GET "lock:show:123"

// User's shopping cart (hash)
HSET "cart:user:456" "show:789" '{"seats": [1,2,3], "total": 1500}'

// Available seats per show (sorted set with score=seat_number)
ZADD "available:show:123" 0 "seat_A1" 0 "seat_A2" 0 "seat_A3"
ZREM "available:show:123" "seat_A1"  ; Remove when booked

// Leaderboard of top movies by bookings
ZADD "leaderboard:movies" 10000 "movie:1" 8500 "movie:2" 7200 "movie:3"

// Pub/Sub for real-time updates
PUBLISH "show:123:updates" '{"event": "seat_booked", "seat": "A1"}'
SUBSCRIBE "show:123:updates"
```

### Eviction Policies

When Redis hits `maxmemory`, it needs to evict keys. Policies:

1. **noeviction**: No eviction, return errors on write (DON'T USE)
2. **allkeys-lru**: Evict least recently used keys (good default)
3. **allkeys-lfu**: Evict least frequently used keys
4. **volatile-lru**: Evict LRU keys with TTL set
5. **volatile-lfu**: Evict LFU keys with TTL set
6. **volatile-ttl**: Evict keys with TTL soonest to expire
7. **volatile-random**: Random eviction among keys with TTL

**Configuration:**
```
maxmemory 1gb
maxmemory-policy allkeys-lru
```

**Movie Booking tuning:**
```
# Short-lived data (locks, carts)
volatile-lru better → evict oldest locks first

# Long-lived data (leaderboards, inventory)
allkeys-lru better → evict least-accessed movies
```

### Redis Cluster Mode

Single Redis is a single point of failure. Cluster mode distributes data across nodes.

```
Cluster with 6 nodes (3 primary, 3 replica):

Primary 1 (slots 0-5460) ── Replica 1
Primary 2 (slots 5461-10922) ── Replica 2
Primary 3 (slots 10923-16383) ── Replica 3
```

**Slot allocation:** Keys are hashed to slots `hash_slot(key) = CRC16(key) % 16384`

**Benefits:**
- Horizontal scaling (distribute across nodes)
- High availability (replicas handle failures)
- No single point of failure

**Tradeoffs:**
- Complexity (multi-key operations harder)
- Network overhead (operations span nodes)
- Rebalancing is complex

### Redis Persistence

**RDB (Redis Database):** Snapshots at intervals
```
save 900 1        ; Save if 1 key changed in 900 seconds
save 300 10       ; Save if 10 keys changed in 300 seconds
save 60 10000     ; Save if 10K keys changed in 60 seconds
```

Pros: Compact, fast to load, good for backups
Cons: Data loss if crash occurs (you lose recent changes), CPU intensive during save

**AOF (Append-Only File):** Log every write operation
```
appendonly yes
appendfsync everysec    ; Flush to disk every second
```

Pros: Better durability (per-second), fault-tolerant
Cons: Larger file, slower, can be rewrit expensive

**Production recommendation:**
```
# RDB for snapshots (backups every hour)
save 3600 1

# AOF for safety (log every command)
appendonly yes
appendfsync everysec
```

For movie booking (bookings are critical):
```
Use both RDB + AOF
Replica on different physical server
Monitor replication lag
Alert if replica falls behind
```

---

## CDN and Edge Caching

CDN (Content Delivery Network) caches content at edge locations geographically close to users.

### Cache Headers

HTTP headers control caching behavior:

**Cache-Control:**
```
Cache-Control: max-age=3600              ; Cache for 1 hour
Cache-Control: public, max-age=86400    ; Public cache for 1 day
Cache-Control: private, max-age=600     ; Only browser cache, 10 min
Cache-Control: no-cache                 ; Must revalidate with origin
Cache-Control: no-store                 ; Don't cache at all
```

**ETag (Entity Tag):** Hash of content
```
Response: ETag: "123abc"

Later Request includes:
If-None-Match: "123abc"

Origin responds:
304 Not Modified           ; If ETag matches, use cached version
```

**Last-Modified:**
```
Response: Last-Modified: Wed, 26 Mar 2024 10:30:00 GMT

Later Request:
If-Modified-Since: Wed, 26 Mar 2024 10:30:00 GMT

304 Not Modified or new content
```

### Movie Booking CDN Strategy

```go
// Static content (images, CSS, JS)
Cache-Control: public, max-age=31536000     ; 1 year (use versioned filenames)

// Movie posters, trailers
Cache-Control: public, max-age=604800       ; 1 week

// Movie reviews, ratings (updated infrequently)
Cache-Control: public, max-age=3600         ; 1 hour

// Seat availability (changes constantly)
Cache-Control: no-cache                     ; Always check origin
or
Cache-Control: private, max-age=5           ; 5 seconds only

// Personalized booking page
Cache-Control: private, no-cache            ; User-specific
```

### Cache Invalidation at Edge

**Purge:** Immediately remove from all edge locations
```
CDN.Purge("movies/poster/123")  ; Removes from cache
```

**Versioning:** Use content hash in URL
```
/images/poster-movie-123-abc123def.jpg      ; Hash changes when content changes
/images/poster-movie-123-abc123def2.jpg     ; New version automatically goes to CDN
```

### Origin Shield

An extra cache layer between edge caches and origin, reducing origin load.

```
User → Edge (cache miss) → Origin Shield (cache miss) → Origin

Second request at different edge:
User → Edge (cache miss) → Origin Shield (cache hit!)
```

Reduces origin traffic by 50-80% in some cases.

---

## Message Queues

Decouple producers and consumers. Allow asynchronous processing, handle spikes.

### Kafka Deep Dive

Kafka is a distributed log. Messages are appended to topics, which are split into partitions.

**Architecture:**
```
Producer → Topic: movie_bookings
              ├── Partition 0: [msg1, msg2, msg5, ...]
              ├── Partition 1: [msg3, msg6, ...]
              └── Partition 2: [msg4, msg7, ...]

Consumer Group 1:
  Consumer A reads Partition 0
  Consumer B reads Partition 1
  Consumer C reads Partition 2

Consumer Group 2:
  Consumer D reads Partition 0
  Consumer E reads Partition 1
  Consumer F reads Partition 2
```

**Movie Booking Flow:**
```go
// Producer: Booking service publishes bookings
producer.Send(ctx, &kafka.Message{
    Topic: "movie_bookings",
    Key:   []byte("show:" + showID),  ; Same show goes to same partition
    Value: bookingJSON,
})

// Consumer 1: Email notifications
consumer.Subscribe(ctx, []string{"movie_bookings"}, "email_group")
for msg := range consumer.Messages() {
    sendBookingConfirmationEmail(msg.Value)
}

// Consumer 2: Analytics
consumer.Subscribe(ctx, []string{"movie_bookings"}, "analytics_group")
for msg := range consumer.Messages() {
    updateAnalyticsDashboard(msg.Value)
}
```

**Exactly-once semantics:**

Without exactly-once, messages can be processed twice (or zero times) on failures.

Solution: Idempotent processing with deduplication.

```go
// Track processed message IDs
type BookingProcessor struct {
    db database
    dedup map[string]bool  // In production: Redis or DB
}

func (bp *BookingProcessor) Process(msg *Message) error {
    booking := parseBooking(msg.Value)

    // Check if already processed
    if bp.dedup[booking.ID] {
        return nil  // Already processed, skip
    }

    // Process
    if err := bp.db.SaveBooking(booking); err != nil {
        return err  // Retry
    }

    // Mark as processed
    bp.dedup[booking.ID] = true
    return nil
}
```

### RabbitMQ vs Kafka vs NATS

| Aspect | RabbitMQ | Kafka | NATS |
|--------|----------|-------|------|
| **Architecture** | Message broker | Distributed log | Simple pub/sub |
| **Durability** | Default durable | Very durable | In-memory |
| **Consumer Groups** | Yes (but complex) | Excellent | No |
| **Replay** | No | Yes (log retention) | No (NATS Streaming has it) |
| **Latency** | Low | Higher (batch) | Ultra-low |
| **Scaling** | Per-queue | Partitions | Simple |
| **Use Case** | Task queues, RPC | Event streams | Real-time signals |

**Movie Booking choice:**

- Bookings (must not lose): **Kafka** (durable, can replay)
- Seat locks (ephemeral): **NATS** (fast, doesn't matter if lost)
- Email notifications: **RabbitMQ** or **Kafka** (needs delivery guarantee)
- Real-time updates: **NATS** (low latency)

---

## Load Balancing

Distribute requests across multiple servers.

### L4 vs L7

**L4 (Transport layer):** Balances by IP/port
```
Client → Load Balancer (examines TCP headers)
  ├── 192.168.1.1:5000 → Server A
  ├── 192.168.1.2:5001 → Server B
  └── 192.168.1.3:5002 → Server C
```

Pros: Very fast, simple
Cons: Can't make intelligent routing decisions, sticky connections require additional work

**L7 (Application layer):** Balances by HTTP headers, URL paths, etc.
```
GET /api/movies → Route to microservice A
GET /api/bookings → Route to microservice B
GET /static/* → Route to CDN
```

Pros: Intelligent routing, path-based, header-based, weight-based
Cons: Higher latency (must inspect request body)

### Load Balancing Algorithms

**Round-robin:** Distribute sequentially
```
1st request → Server 1
2nd request → Server 2
3rd request → Server 3
4th request → Server 1  (cycle)
```

Simple, fair, but doesn't account for server capacity.

**Least-connections:** Route to server with fewest active connections
```
Server A: 10 active connections
Server B: 5 active connections
Server C: 8 active connections

New request → Server B
```

Better for variable request durations.

**Weighted round-robin:** Servers have capacity weights
```
Server A (weight 5): gets 5/12 of requests
Server B (weight 4): gets 4/12 of requests
Server C (weight 3): gets 3/12 of requests
```

Useful when servers have different capacity.

**Consistent hashing:** Same client goes to same server
```
hash(user_id) % num_servers = server
```

Good for stateful services or cache affinity.

**Movie Booking example:**
```
/api/movies → All servers (stateless), least-connections algorithm
/api/bookings → Consistent hash by user_id (session affinity)
/api/payments → Dedicated payment servers, round-robin with health checks
```

---

## Auto-scaling

Scale up/down based on metrics.

### Metrics-Based Scaling

**CPU-based:**
```
Trigger scale-up: CPU > 70% for 2 minutes
Trigger scale-down: CPU < 30% for 5 minutes
Min replicas: 2
Max replicas: 20
```

Simple, but CPU isn't always the bottleneck.

**Queue depth-based:**
```
Trigger scale-up: Queue > 100 messages
Add one server per 50 messages in queue
```

Excellent for async workloads.

**Latency-based:**
```
Trigger scale-up: p99 latency > 500ms for 1 minute
Trigger scale-down: p99 latency < 100ms for 5 minutes
```

Proactive, customer-facing.

**Custom metrics:**
```
Trigger scale-up: Seat lock contention > 10% for 1 minute
Trigger scale-up: Payment gateway queue > 500
```

### Predictive Scaling

Instead of reacting to load, predict it.

```
Time-based: Scale up before noon show booking surge
Pattern-based: More users on weekends
Event-based: Major movie release → expect 5x traffic
```

Reduces startup time, ensures capacity when needed.

**Movie Booking example:**
```
// Friday-Saturday nights: scale up at 4pm
cron.Schedule("0 16 * * 5-6", scaleUp)

// Monday-Thursday: baseline
cron.Schedule("0 2 * * 1-4", scaleDown)

// Major release (precomputed): scale up 1 hour before
event.OnMajorReleaseScheduled(func(release) {
    schedule(scaleUp, release.ReleaseTime.Add(-1*time.Hour))
})
```

---

## Database Indexing

Indexes speed up queries by avoiding full table scans.

### B-tree Indexes (Standard)

Balanced tree structure, keeps data ordered.

```
CREATE INDEX idx_user_email ON users(email);

Tree:
         [J]
        /   \
      [E]   [P]
     / | \  / | \
    A C G  L N R T

Search for email="john@example.com":
Compare at root (J) → go left
Compare at E → go right
Compare at G → go right
Found! Leaf node contains row
```

Time complexity: O(log N)

**Best for:** Equality checks, range queries, sorting

### Hash Indexes

Maps key to bucket location directly.

```
CREATE INDEX idx_user_id USING HASH ON users(id);

hash(123) = 5 → bucket 5 contains row 123
```

Time complexity: O(1) average

**Best for:** Equality checks only
**Limitation:** Can't do range queries or sorting

### GIN (Generalized Inverted Index)

For composite types: arrays, JSON, full-text search.

```
CREATE INDEX idx_tags ON movies USING gin(tags);

movies:
1: {tags: ["action", "thriller"]}
2: {tags: ["romance", "drama"]}
3: {tags: ["action", "drama"]}

Inverted index:
"action" → [1, 3]
"thriller" → [1]
"romance" → [2]
"drama" → [2, 3]

Query: tags contains "action" AND "drama"
→ Intersection of [1,3] and [2,3]
→ Movie 3
```

### GiST (Generalized Search Tree)

For geometric data, nearest-neighbor queries.

```
CREATE INDEX idx_theater_location
  ON theaters USING gist(location);

SELECT * FROM theaters
WHERE location <-> point(28.6, 77.2) < 5  ; Nearest 5km
```

### Covering Indexes

Index includes data, no need to fetch table.

```
-- Without covering:
CREATE INDEX idx_user_email ON users(email);
Query: SELECT id, email, created_at WHERE email = 'x@y'
→ Index lookup finds id
→ Fetch from table to get created_at

-- With covering:
CREATE INDEX idx_user_email_cover
  ON users(email) INCLUDE (created_at);
→ Index lookup finds id, email, created_at directly
→ No table fetch needed
```

### Partial Indexes

Index only rows matching a condition.

```
-- All deleted users
CREATE INDEX idx_active_bookings
  ON bookings(user_id) WHERE status != 'cancelled';

-- Bookings in last 30 days
CREATE INDEX idx_recent_bookings
  ON bookings(user_id) WHERE created_at > now() - interval '30 days';
```

Smaller index, faster writes.

### Query Optimization with EXPLAIN ANALYZE

```sql
EXPLAIN ANALYZE
SELECT user_id, COUNT(*)
FROM bookings
WHERE show_id = 123
GROUP BY user_id;

Output:
Seq Scan on bookings (cost=0.00..8000.00 rows=1000)  ← BAD
  Filter: (show_id = 123)

After adding index:
CREATE INDEX idx_bookings_show ON bookings(show_id);

Index Scan using idx_bookings_show (cost=0.10..10.00 rows=100)  ← GOOD
```

---

## Production Scenario: Movie Booking System

Scaling from 100 to 100,000 concurrent users.

### Phase 1: 100 Users (Single Server)

**Architecture:**
```
Users → Load Balancer (SSL) → 1 Application Server → 1 PostgreSQL DB → 1 Redis Cache
                                   (4 cores, 16GB RAM)         (20GB)   (4GB)
```

**Bottleneck analysis:**
- Database: handles ~1,000 QPS
- Adequate for 100 concurrent users (each user ~10 QPS during peak booking)

**Implementation:**
```go
// Simple caching
func GetMovies(ctx context.Context) ([]Movie, error) {
    // Try Redis
    movies, _ := redis.Get(ctx, "all_movies")
    if movies != nil {
        return movies, nil
    }

    // Load from DB
    movies, err := db.GetMovies(ctx)
    if err == nil {
        redis.Set(ctx, "all_movies", movies, 1*time.Hour)
    }
    return movies, err
}
```

### Phase 2: 1,000 Users

**Issues at 100 users:**
- Database CPU at 40%, reaching limits
- Redis at 50% capacity
- Single point of failure

**Scaling strategy:**
```
Add 2 more application servers (round-robin load balancing)
Add 1 read replica for reads
Add Redis replica for backup
```

**Architecture:**
```
Users → Load Balancer → App Server 1
                    → App Server 2
                    → App Server 3
         ↓
Primary DB (writes) ← RW → Read Replica (reads)
         ↓
Redis Primary ← RW → Redis Replica (backup)
```

**Implementation changes:**
```go
// Route reads to replica
func GetSeatAvailability(ctx context.Context, showID string) ([]Seat, error) {
    // Use read replica (eventual consistency is fine for inventory)
    return db.ReadReplica.GetSeats(ctx, showID)
}

// Route writes to primary
func BookSeats(ctx context.Context, booking *Booking) error {
    return db.Primary.SaveBooking(ctx, booking)
}
```

### Phase 3: 10,000 Users

**Issues at 1,000:**
- Database still at 60% CPU (write bottleneck)
- Read replica lagging 100-200ms
- Redis at 80% capacity
- Application servers each using 100GB/s network (starting to hit limits)

**Scaling strategy:**
- Shard bookings by show_id
- Implement caching for seat availability
- Use connection pooling aggressively
- Add pgBouncer proxy

**Architecture:**
```
Users → LB → [App1, App2, App3, App4, App5]
         ↓
    PgBouncer (connection pooling)
         ↓
    Primary 1 (shows 1-1M)    Primary 2 (shows 1M-2M)    Primary 3 (shows 2M-3M)
         ↓                          ↓                          ↓
    Replica 1                  Replica 2                  Replica 3

Redis Cluster (3 nodes with replicas)
```

**Shard key selection:**
```go
func GetShardForShow(showID string) int {
    return hash(showID) % 3  // 3 database shards
}

func BookSeats(ctx context.Context, booking *Booking) error {
    shard := GetShardForShow(booking.ShowID)
    db := shards[shard]
    return db.SaveBooking(ctx, booking)
}
```

### Phase 4: 100,000 Users

**Issues at 10,000:**
- Each database shard at 70% capacity
- Still centralized Redis (even cluster mode has limits)
- Network bandwidth per application server exceeds limits
- Need to split by geography

**Scaling strategy:**
- Shard both shows (by ID) and users (by region/geography)
- Distribute Redis cluster globally
- Add CDN for static content
- Implement write-through caching for seat availability
- Add circuit breakers and bulkheads

**Architecture:**
```
[Mumbai Users] ──┐
[Delhi Users] ───┤→ India LB → India DC
[Bangalore Users]┘
    ↓
  India Shards (1, 2, 3)
  India Redis Cluster

[London Users] ──┐
[Paris Users] ───┤→ EU LB → EU DC
[Berlin Users] ──┘
    ↓
  EU Shards (1, 2, 3)
  EU Redis Cluster (replicated from India)
```

**Circuit breaker pattern (prevent cascading failures):**
```go
type CircuitBreaker struct {
    failureThreshold int
    cooldownPeriod   time.Duration
    state            string  // "closed", "open", "half-open"
    lastFailureTime  time.Time
    failureCount     int
}

func (cb *CircuitBreaker) Execute(fn func() error) error {
    if cb.state == "open" {
        if time.Since(cb.lastFailureTime) > cb.cooldownPeriod {
            cb.state = "half-open"  // Try again
        } else {
            return fmt.Errorf("circuit open")
        }
    }

    err := fn()
    if err != nil {
        cb.failureCount++
        if cb.failureCount >= cb.failureThreshold {
            cb.state = "open"
            cb.lastFailureTime = time.Now()
        }
        return err
    }

    cb.failureCount = 0
    cb.state = "closed"
    return nil
}

// Usage
func GetSeats(ctx context.Context, showID string) ([]Seat, error) {
    var seats []Seat
    err := seatCB.Execute(func() error {
        var err error
        seats, err = db.GetSeats(ctx, showID)
        return err
    })
    return seats, err
}
```

---

## What Breaks in Production

### Hot Partitions

One shard gets disproportionate traffic.

**Scenario:**
```
Movie "Avatar 3" releases → everyone books simultaneously
Shard 3 (Avatar 3) gets 80% of traffic
Shards 1 & 2 idle at 5% CPU
```

**Solutions:**
- Sub-partition: Split "Avatar 3" across multiple shards
- Caching: Cache seat availability aggressively
- Burst capacity: Pre-allocate extra capacity for known blockbusters

### Cache Stampede

Popular key expires with concurrent requests.

**Scenario:**
```
"Avatar 3" seat availability cached, 10,000 QPS
Cache expires at 12:00:00.000

All 10,000 requests in-flight miss cache
All 10,000 hit database simultaneously
Database overwhelmed → cascading failure
```

**Solutions:**
- Probabilistic expiration (refresh at 90% TTL)
- Distributed locking (only one refresh)
- Secondary cache layer

### Thundering Herd

All servers crash, all restart simultaneously, all query database.

**Scenario:**
```
Redis cluster goes down
100 application servers restart
All 100 try to fill cache from database
Database CPU spikes to 100% → timeout → cascading restart
```

**Solutions:**
- Staggered restart (restart 10% per minute)
- Circuit breakers (don't query DB if Redis is down)
- Fallback to stale data

### Split Brain in Replicas

Primary and replica disagree (network partition).

**Scenario:**
```
Booking written to Primary
Write not replicated yet
Network partition occurs
Client reads from Replica: booking not visible
Later: replicas reconcile, conflict occurs
```

**Solutions:**
- Quorum reads (require confirmation from multiple replicas)
- Write acknowledgment wait (only return after replication)
- Monotonic reads (same client always reads from same replica)

### Database Connection Exhaustion

All application servers max out connection pools.

**Scenario:**
```
100 app servers × 100 pool_size = 10,000 connections
Database max_connections = 200
Connections refused → all requests timeout
```

**Solutions:**
- pgBouncer proxy (multiplex connections)
- Smaller pool sizes (20 instead of 100)
- Connection eviction policies

---

## Interview Questions

1. **Design a caching strategy for a movie booking system handling 100,000 concurrent users. What are the trade-offs between cache-aside, write-through, and write-behind approaches?**

   Model answer:
   - Cache-aside: Simple, but risk of cache stampede on key expiration. Use for read-heavy, infrequent writes (user profiles)
   - Write-through: Consistent, but slower writes. Risk if cache is down. Use for critical data (account balance)
   - Write-behind: Fast, but data loss risk. Use for non-critical, eventually-consistent data (analytics, notifications)

   For movie booking:
   - Seat availability: cache-aside (reads >> writes before booking)
   - User profile: write-through (consistency important)
   - Booking history: write-behind (eventual consistency acceptable)
   - Prevent cache stampede: use locks or probabilistic refresh

2. **You have a PostgreSQL database at 80% CPU with 10,000 QPS read-heavy traffic. Your team has 1 week to scale. What's your approach?**

   Model answer (prioritize by effort/impact):
   - Day 1-2: Add read replicas (quick, 60% CPU reduction)
   - Day 2-3: Implement caching layer (Redis, 80% reduction for cache hits)
   - Day 3-4: Optimize slow queries (EXPLAIN ANALYZE, add indexes)
   - Day 4-5: Implement connection pooling (pgBouncer)
   - Day 6-7: Plan database sharding for next phase

   Don't immediately jump to sharding (expensive, risky).

3. **Your Redis cache is at 90% capacity. You have 3 options: (a) buy bigger Redis, (b) implement Redis cluster, (c) implement local application-level caching. What do you choose and why?**

   Model answer:
   - Option A: Simple, works up to hardware limits. When does limit get hit again?
   - Option B: Solves capacity, adds complexity (cache misses on resharding, latency)
   - Option C: Reduces centralized load, but complexity (consistency between servers)

   Best: Combination.
   - Immediate (1-2 weeks): Implement local LRU cache for hot keys (movies, leaderboards)
   - Medium (1 month): Add Redis cluster (background work)
   - Long-term: Monitor and plan next scaling

4. **Explain consistent hashing and when it's necessary. Could you build the movie booking system without it?**

   Model answer:
   - Consistent hashing: when adding/removing servers, only ~1/N of keys rehash (vs all keys with modulo)
   - For Redis: during resharding, old hash(key) % N breaks. Need rehashing.
   - Alternative without consistent hashing: always rehash everything (downtime), or use stateless services

   Movie booking:
   - If stateless: can live without consistent hashing
   - If Redis Cluster: need it (or use built-in cluster support)
   - Trade-off: complexity vs operational smoothness

5. **Your movie booking system has seat locking (pessimistic locking). Under high concurrency, what failure modes occur? How would you detect and mitigate them?**

   Model answer:
   - Failure mode 1: Lock timeout (user locks seat, forgets to confirm, seat locked for 5min)
     - Mitigation: use short TTL on locks, allow users to extend TTL
   - Failure mode 2: Deadlock (user A locks seat 1, B locks seat 2, A waits for 2, B waits for 1)
     - Mitigation: always lock in consistent order (sort seat IDs)
   - Failure mode 3: Lock server failure (Redis goes down, locks released)
     - Mitigation: dual-write to database + Redis, replicate Redis

   Detection: monitor lock contention ratio, stuck transaction duration, failed lock acquisitions.

6. **Compare Kafka vs RabbitMQ for a movie booking notification system. Which would you choose and why?**

   Model answer:
   - Kafka: Replay, durability, high throughput (good for analytics)
   - RabbitMQ: Simple, lower latency, flexible routing (good for task queues)

   For notifications:
   - If want to replay (re-send old notifications): Kafka
   - If each notification must deliver exactly-once: RabbitMQ (simpler)
   - If high volume (100K notifications/sec): Kafka
   - If low volume (10K/sec): RabbitMQ

   Movie booking: Hybrid
   - Bookings → Kafka (audit trail, replay)
   - Notifications → RabbitMQ (guaranteed delivery)

