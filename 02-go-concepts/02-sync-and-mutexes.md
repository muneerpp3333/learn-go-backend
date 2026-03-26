# Sync Primitives and Mutexes: Building Thread-Safe Systems

## Problem: Protecting Shared State

You're building a WhatsApp ops platform where:
- Multiple goroutines update user presence (online/offline) simultaneously
- A real-time dashboard reads presence state constantly
- Ticket counters must be thread-safe across 100 goroutines
- Configuration changes (rate limits, feature flags) must be visible immediately to all workers

The challenge: Go's mantra is "don't communicate by sharing memory; share memory by communicating." But sometimes shared state is unavoidable. The `sync` package provides primitives to do it correctly.

---

## Part 1: sync.Mutex vs sync.RWMutex

### The Reader-Writer Problem

Many goroutines want to **read** data frequently, but **writes** are rare. Using a plain Mutex forces readers to wait for each other unnecessarily.

### sync.Mutex: Basic Mutual Exclusion

A Mutex ensures only one goroutine holds the lock at a time.

```go
type UserPresence struct {
    mu    sync.Mutex
    users map[string]bool // true = online
}

func (up *UserPresence) SetOnline(userID string, online bool) {
    up.mu.Lock()
    defer up.mu.Unlock()
    up.users[userID] = online
}

func (up *UserPresence) IsOnline(userID string) bool {
    up.mu.Lock()
    defer up.mu.Unlock()
    return up.users[userID]
}
```

**Cost**: Each read waits for all other reads to finish. Under high read load, contention increases and throughput drops.

**Lock hold time**: Keep critical sections minimal. Avoid I/O, network calls, or heavy computation under lock.

### sync.RWMutex: Reader-Writer Locks

Allow multiple readers, but exclusive writer access.

```go
type UserPresenceRW struct {
    mu    sync.RWMutex
    users map[string]bool
}

func (up *UserPresenceRW) SetOnline(userID string, online bool) {
    up.mu.Lock()        // Exclusive lock
    defer up.mu.Unlock()
    up.users[userID] = online
}

func (up *UserPresenceRW) IsOnline(userID string) bool {
    up.mu.RLock()        // Shared lock
    defer up.mu.RUnlock()
    return up.users[userID]
}

func (up *UserPresenceRW) AllOnline() []string {
    up.mu.RLock()
    defer up.mu.RUnlock()

    result := make([]string, 0, len(up.users))
    for user, online := range up.users {
        if online {
            result = append(result, user)
        }
    }
    return result
}
```

**Advantage**: 1000 concurrent readers don't block each other. Write latency increases (must wait for all readers).

**When to use RWMutex**:
- Read:Write ratio > 10:1
- Readers are numerous and concurrent
- Reads are quick (no I/O under lock)

**When to use Mutex**:
- Balanced read/write ratio
- Write frequency is moderate
- Lock contention is low

### Mutex Internals

A Mutex is a small structure:
- A locked state (1 bit)
- A queue of waiting goroutines
- A fair scheduling guarantee (recent Go versions)

Under contention, lock acquisition involves:
1. Try CAS (compare-and-swap) to acquire lock
2. If fail, add goroutine to waiter queue
3. Park the goroutine
4. Woken up in order (fairness)

**Cost**: ~50-200ns per Lock/Unlock pair without contention. With contention, adds 1-10μs per acquisition.

---

## Part 2: sync.Map — Lock-Free Maps

For highly concurrent scenarios with disjoint key sets, `sync.Map` is a lock-free alternative.

```go
type Cache struct {
    data sync.Map
}

func (c *Cache) Get(key string) (interface{}, bool) {
    return c.data.Load(key)
}

func (c *Cache) Set(key string, value interface{}) {
    c.data.Store(key, value)
}

func (c *Cache) Delete(key string) {
    c.data.Delete(key)
}
```

### How sync.Map Works

Internally, `sync.Map` maintains two maps:
- **read map**: Immutable, lock-free
- **dirty map**: Mutable, protected by mutex

Operations:
- **Load**: Checks read map (fast), falls back to dirty map if miss
- **Store**: Updates both maps, but dirty map requires lock
- **Delete**: Marks as deleted in read map, deletes from dirty map

When dirty map has too many stale entries, it's promoted to read map.

### When to Use sync.Map

**Good cases**:
- High read concurrency, few writes
- Keys are disjoint (no contention on same key)
- No need to iterate over all keys

**Bad cases**:
- Frequent writes to same keys (contention)
- Need to range over all entries
- Want atomic snapshots (Range won't give consistent view)

```go
// ANTI-PATTERN: Range is not atomic
var m sync.Map
m.Range(func(key, value interface{}) bool {
    // Map may have changed between range calls
    return true
})
```

---

## Part 3: sync.Once — Initialization Patterns

Ensure a block of code runs exactly once, even with concurrent calls.

```go
type Singleton struct {
    value string
}

var (
    instance *Singleton
    once     sync.Once
)

func GetSingleton() *Singleton {
    once.Do(func() {
        instance = &Singleton{value: "initialized"}
    })
    return instance
}
```

### Lazy Loading with Once

```go
type DatabasePool struct {
    pool *pgx.Pool
    once sync.Once
    err  error
}

func (db *DatabasePool) GetPool() (*pgx.Pool, error) {
    db.once.Do(func() {
        db.pool, db.err = pgx.NewPool(context.Background(),
            "postgres://user:pass@localhost/dbname")
    })
    return db.pool, db.err
}
```

### Double-Check Locking Anti-Pattern

```go
// BAD: Prone to race conditions
if db.pool == nil {
    db.mu.Lock()
    if db.pool == nil {
        db.pool, _ = pgx.NewPool(ctx, connString)
    }
    db.mu.Unlock()
}

// GOOD: Use Once
var once sync.Once
once.Do(func() {
    db.pool, _ = pgx.NewPool(ctx, connString)
})
```

**Cost**: ~10-50ns per call (cheap). Serializes first call, but subsequent calls are lock-free.

---

## Part 4: sync.Pool — Object Reuse for GC Efficiency

Reduce garbage collection pressure by reusing objects across goroutines.

### Use Case: Buffer Pool

```go
var bufferPool = sync.Pool{
    New: func() interface{} {
        return new(bytes.Buffer)
    },
}

func ReadRequest(r *http.Request) ([]byte, error) {
    buf := bufferPool.Get().(*bytes.Buffer)
    defer bufferPool.Put(buf)

    buf.Reset()
    _, err := io.Copy(buf, r.Body)
    if err != nil {
        return nil, err
    }

    return buf.Bytes(), nil
}
```

### Pool for HTTP Body Processing

```go
type JSONDecoder struct {
    pool *sync.Pool
}

func NewJSONDecoder() *JSONDecoder {
    return &JSONDecoder{
        pool: &sync.Pool{
            New: func() interface{} {
                return new(json.Decoder)
            },
        },
    }
}

func (jd *JSONDecoder) Decode(reader io.Reader) (interface{}, error) {
    decoder := jd.pool.Get().(*json.Decoder)
    defer jd.pool.Put(decoder)

    // Reuse decoder state
    var result interface{}
    err := decoder.Decode(&result)
    return result, err
}
```

### Pool Internals and Gotchas

`sync.Pool` is designed for **per-P (per logical processor) object caches**. Each P has its own pool queue.

**Important**: Objects in the pool are eligible for GC if no other references exist. Don't store pointers to pool objects beyond the function that uses them.

```go
// DANGER: Storing reference to pool object beyond function scope
func leakyPoolUsage() *bytes.Buffer {
    buf := bufferPool.Get().(*bytes.Buffer)
    // Reference escapes function, but buffer is pool-managed
    return buf  // Buffer might be reused elsewhere!
}

// SAFE: Keep buffer only within function
func safePoolUsage(r io.Reader) error {
    buf := bufferPool.Get().(*bytes.Buffer)
    defer bufferPool.Put(buf)
    _, err := io.Copy(buf, r)
    return err
}
```

**Cost**: ~5-20ns per Get/Put (very cheap). Reduces GC pause times by 10-50% in allocation-heavy workloads.

---

## Part 5: sync.WaitGroup — Coordination Patterns

Synchronize multiple goroutines to a completion point.

```go
func fanOutFanIn(items []string) {
    var wg sync.WaitGroup

    for _, item := range items {
        wg.Add(1)
        go func(item string) {
            defer wg.Done()
            process(item)
        }(item)
    }

    wg.Wait()  // Block until all Done() calls match Add() calls
}
```

### Common WaitGroup Bugs

**Bug 1: Adding after waiting**

```go
// PANIC: fatal error: sync: WaitGroup is reused before previous Wait has returned
var wg sync.WaitGroup
wg.Add(1)
go func() {
    defer wg.Done()
    process()
}()

wg.Wait()
wg.Add(1)  // ERROR: counter negative
```

Fix: Create new WaitGroup for each phase or reuse carefully:

```go
var wg sync.WaitGroup
for batch := 0; batch < 10; batch++ {
    for i := 0; i < 5; i++ {
        wg.Add(1)
        go func(n int) {
            defer wg.Done()
            process(n)
        }(i)
    }
    wg.Wait()  // Wait for batch to complete
}
```

**Bug 2: Forgetting Add/Done**

```go
// DEADLOCK: Wait hangs forever because Done count never matches Add
var wg sync.WaitGroup
wg.Add(1)
go func() {
    defer wg.Done()
    process()
}()
// Oops, Add(1) but expected 2 concurrent tasks

wg.Wait()  // Hangs
```

**Bug 3: Negative counter**

```go
// PANIC: negative WaitGroup counter
var wg sync.WaitGroup
wg.Done()  // Done without Add
```

---

## Part 6: sync.Cond — Condition Variables

Signal multiple goroutines waiting for a condition. Rarely used but important for interviews.

```go
type Queue struct {
    mu    sync.Mutex
    items []interface{}
    cond  *sync.Cond
}

func NewQueue() *Queue {
    q := &Queue{}
    q.cond = sync.NewCond(&q.mu)
    return q
}

func (q *Queue) Push(item interface{}) {
    q.mu.Lock()
    defer q.mu.Unlock()

    q.items = append(q.items, item)
    q.cond.Signal()  // Wake one waiter
}

func (q *Queue) Pop() interface{} {
    q.mu.Lock()
    defer q.mu.Unlock()

    for len(q.items) == 0 {
        q.cond.Wait()  // Release lock, wait for signal, reacquire lock
    }

    item := q.items[0]
    q.items = q.items[1:]
    return item
}

func (q *Queue) PopAll() []interface{} {
    q.mu.Lock()
    defer q.mu.Unlock()

    for len(q.items) == 0 {
        q.cond.Wait()
    }

    result := q.items
    q.items = nil
    return result
}

func (q *Queue) Broadcast() {
    q.mu.Lock()
    defer q.mu.Unlock()
    q.cond.Broadcast()  // Wake all waiters
}
```

**When to use**: Broadcasting to multiple goroutines. Most code should use channels instead.

**Cost**: Similar to mutex (~100-300ns per operation with contention).

---

## Part 7: Atomic Operations — Lock-Free Counters

The `sync/atomic` package provides lock-free operations for simple values.

### atomic.Counter (Go 1.24+)

```go
type Metrics struct {
    requests atomic.Int64
    errors   atomic.Int64
}

func (m *Metrics) RecordRequest() {
    m.requests.Add(1)
}

func (m *Metrics) RecordError() {
    m.errors.Add(1)
}

func (m *Metrics) GetMetrics() (requests, errors int64) {
    return m.requests.Load(), m.errors.Load()
}
```

### atomic.Value — Configuration Hot-Reload

```go
type Config struct {
    RateLimit int
    Timeout   time.Duration
    Features  map[string]bool
}

type AppConfig struct {
    current atomic.Value  // Holds *Config
}

func (ac *AppConfig) SetConfig(cfg *Config) {
    ac.current.Store(cfg)
}

func (ac *AppConfig) GetConfig() *Config {
    return ac.current.Load().(*Config)
}

// In a goroutine, periodically reload from file/API
func (ac *AppConfig) reloadLoop(ctx context.Context) {
    ticker := time.NewTicker(1 * time.Minute)
    defer ticker.Stop()

    for range ticker.C {
        cfg, err := loadConfigFromAPI()
        if err == nil {
            ac.SetConfig(cfg)
        }
    }
}
```

### Compare-and-Swap

```go
type Flag struct {
    state atomic.Bool
}

func (f *Flag) TrySet() bool {
    // Atomically set to true only if currently false
    return f.state.CompareAndSwap(false, true)
}

// Usage: leader election
func leaderElection(peers []string) bool {
    flag := &Flag{}
    return flag.TrySet()  // Returns true only for one peer
}
```

---

## Part 8: The Race Detector

Go's race detector catches data races by instrumenting every memory operation.

### Enabling the Race Detector

```bash
go test -race ./...
go run -race main.go
```

### Example: Detecting a Race

```go
func testRace(t *testing.T) {
    var value int

    go func() {
        value = 1  // Write
    }()

    value = 2  // Concurrent read/write -> RACE!
}

// Output with -race:
// WARNING: DATA RACE
// Write at 0x00c000120020 by goroutine 7:
//   main.testRace.func1()
// Previous write at 0x00c000120020 by main goroutine:
//   main.testRace()
```

### How -race Works

The race detector:
1. Instruments all memory accesses
2. Tracks which goroutine accessed what memory
3. If two different goroutines access the same memory without synchronization, reports a race

**Cost**: 5-10x slowdown, 2-3x memory overhead. Only use in testing, not production.

**Important**: Race detector has false negatives (doesn't catch all races), but virtually no false positives.

---

## Part 9: Production Code — Concurrent Ticket Counter

Real-world scenario: Track ticket sales across concurrent requests with correct synchronization.

```go
package ticketing

import (
    "context"
    "errors"
    "sync"
    "sync/atomic"
)

// TicketCounter tracks available tickets with different sync strategies
type TicketCounterAtomic struct {
    total     atomic.Int32
    remaining atomic.Int32
}

func NewTicketCounterAtomic(total int32) *TicketCounterAtomic {
    tc := &TicketCounterAtomic{}
    tc.total.Store(total)
    tc.remaining.Store(total)
    return tc
}

func (tc *TicketCounterAtomic) TryBuy(count int32) bool {
    for {
        current := tc.remaining.Load()
        if current < count {
            return false
        }
        if tc.remaining.CompareAndSwap(current, current-count) {
            return true
        }
        // CAS failed, retry
    }
}

func (tc *TicketCounterAtomic) Remaining() int32 {
    return tc.remaining.Load()
}

// TicketCounterMutex uses mutex for more complex operations
type TicketCounterMutex struct {
    mu        sync.RWMutex
    total     int32
    remaining int32
    sold      int32
}

func NewTicketCounterMutex(total int32) *TicketCounterMutex {
    return &TicketCounterMutex{
        total:     total,
        remaining: total,
    }
}

func (tc *TicketCounterMutex) TryBuy(count int32) bool {
    tc.mu.Lock()
    defer tc.mu.Unlock()

    if tc.remaining < count {
        return false
    }

    tc.remaining -= count
    tc.sold += count
    return true
}

func (tc *TicketCounterMutex) GetStats() (remaining, sold int32) {
    tc.mu.RLock()
    defer tc.mu.RUnlock()
    return tc.remaining, tc.sold
}

// RateLimiter using atomic operations
type RateLimiter struct {
    lastRequest atomic.Int64  // Unix nanos
    minInterval int64         // Nanos between requests
}

func NewRateLimiter(rps int) *RateLimiter {
    return &RateLimiter{
        minInterval: int64(1e9 / rps),  // Nanos per request
    }
}

func (rl *RateLimiter) Allow(ctx context.Context) bool {
    now := time.Now().UnixNano()
    last := rl.lastRequest.Load()

    if now-last < rl.minInterval {
        return false
    }

    // Try to update last request time
    if rl.lastRequest.CompareAndSwap(last, now) {
        return true
    }

    return false
}

// TicketPool using sync.Pool for allocation efficiency
type ReservationBuffer struct {
    pool *sync.Pool
}

func NewReservationBuffer() *ReservationBuffer {
    return &ReservationBuffer{
        pool: &sync.Pool{
            New: func() interface{} {
                return &Reservation{
                    UserID: "",
                    Count:  0,
                }
            },
        },
    }
}

type Reservation struct {
    UserID string
    Count  int32
}

func (rb *ReservationBuffer) Get() *Reservation {
    return rb.pool.Get().(*Reservation)
}

func (rb *ReservationBuffer) Put(r *Reservation) {
    r.UserID = ""
    r.Count = 0
    rb.pool.Put(r)
}

// Complete booking system with proper synchronization
type BookingService struct {
    counter TicketCounterMutex
    mu      sync.RWMutex
    orders  map[string]*Order
}

type Order struct {
    ID    string
    Count int32
}

func NewBookingService(totalTickets int32) *BookingService {
    return &BookingService{
        counter: TicketCounterMutex{total: totalTickets, remaining: totalTickets},
        orders:  make(map[string]*Order),
    }
}

func (bs *BookingService) Purchase(userID string, count int32) (bool, error) {
    if bs.counter.TryBuy(count) {
        bs.mu.Lock()
        bs.orders[userID] = &Order{ID: userID, Count: count}
        bs.mu.Unlock()
        return true, nil
    }

    return false, errors.New("not enough tickets")
}

func (bs *BookingService) GetOrders(ctx context.Context) []Order {
    bs.mu.RLock()
    defer bs.mu.RUnlock()

    orders := make([]Order, 0, len(bs.orders))
    for _, order := range bs.orders {
        orders = append(orders, *order)
    }

    return orders
}
```

---

## Part 10: What Breaks at Scale

### Issue 1: Lock Contention

```go
// DANGER: Many goroutines contending for same lock
var mu sync.Mutex
var counter int

for i := 0; i < 1000; i++ {
    go func() {
        for j := 0; j < 1000; j++ {
            mu.Lock()
            counter++
            mu.Unlock()  // Lock duration: ~100ns. Contention adds 1-10μs
        }
    }()
}
```

Fix: Use atomic operations or reduce lock scope:

```go
var counter atomic.Int64  // No lock contention

for i := 0; i < 1000; i++ {
    go func() {
        for j := 0; j < 1000; j++ {
            counter.Add(1)  // ~20ns per operation, no contention
        }
    }()
}
```

### Issue 2: Priority Inversion

A low-priority goroutine holds a lock, blocking a high-priority goroutine.

```go
// DANGER: Low-priority writer blocks high-priority readers
var mu sync.RWMutex
var data map[string]string

// Low-priority writer
go func() {
    for {
        mu.Lock()
        time.Sleep(100 * time.Millisecond)  // Long critical section
        data["key"] = "value"
        mu.Unlock()
    }
}()

// High-priority readers
for i := 0; i < 1000; i++ {
    go func() {
        mu.RLock()
        val := data["key"]
        mu.RUnlock()
    }()
}
```

Fix: Reduce lock hold time or use lock-free structures:

```go
// Use sync.Map instead of RWMutex
var data sync.Map

go func() {
    for {
        // No lock held during sleep
        time.Sleep(100 * time.Millisecond)
        data.Store("key", "value")
    }
}()
```

### Issue 3: Forgotten Unlock

```go
// DANGER: If error path doesn't unlock, deadlock
func process() error {
    mu.Lock()
    // Missing defer mu.Unlock()

    if err := validate(); err != nil {
        return err  // DEADLOCK: Forgot to unlock!
    }

    mu.Unlock()
    return nil
}

// FIXED: Always use defer
func process() error {
    mu.Lock()
    defer mu.Unlock()

    if err := validate(); err != nil {
        return err  // Unlock called by defer
    }

    return nil
}
```

### Issue 4: Copying Locked Structs

```go
// DANGER: Copying a struct with embedded Mutex
type Service struct {
    mu    sync.Mutex
    data  map[string]string
}

svc := &Service{data: make(map[string]string)}
svc.mu.Lock()

copy := *svc  // Copies the Mutex! Both svc and copy now have different mutexes
svc.mu.Unlock()

copy.mu.Lock()  // Locks a different mutex, doesn't protect original data
```

Fix: Never copy locked structs. Pass pointers:

```go
svc := &Service{data: make(map[string]string)}
copy := svc  // Both reference same Service, same Mutex
```

---

## Part 9: Mu Compound Operations and Critical Sections

When protecting multiple related fields, the order of operations matters:

```go
// DANGER: Two separate lock/unlocks create race condition
type BankAccount struct {
    mu       sync.Mutex
    balance  float64
    updated  time.Time
}

func (ba *BankAccount) UnsafeTransfer(amount float64) {
    ba.mu.Lock()
    ba.balance -= amount
    ba.mu.Unlock()

    // RACE: Another goroutine sees balance decreased but updated time old
    // Updated should reflect the change

    ba.mu.Lock()
    ba.updated = time.Now()
    ba.mu.Unlock()
}

// FIXED: Single critical section for both fields
func (ba *BankAccount) Transfer(amount float64) {
    ba.mu.Lock()
    defer ba.mu.Unlock()

    ba.balance -= amount
    ba.updated = time.Now()
}
```

**Principle**: All related mutations must happen in a single critical section. Never separate related updates.

---

## Part 10: Singleflight for Cache Stampede Prevention

When multiple goroutines request the same uncached item simultaneously, all hit the origin, overwhelming it. `singleflight` deduplicates requests:

```go
import "golang.org/x/sync/singleflight"

type MovieCache struct {
    group singleflight.Group
    db    *pgx.Pool
}

func (mc *MovieCache) GetMovie(ctx context.Context, movieID string) (*Movie, error) {
    // Only one goroutine fetches; others wait for result
    val, err, _ := mc.group.Do(movieID, func() (interface{}, error) {
        return mc.fetchFromDB(ctx, movieID)
    })

    if err != nil {
        return nil, err
    }

    return val.(*Movie), nil
}

func (mc *MovieCache) fetchFromDB(ctx context.Context, movieID string) (*Movie, error) {
    var movie Movie
    err := mc.db.QueryRow(ctx, "SELECT id, title FROM movies WHERE id = $1", movieID).
        Scan(&movie.ID, &movie.Title)
    return &movie, err
}

// Usage: 1000 concurrent requests for same movie
// Without singleflight: 1000 DB queries
// With singleflight: 1 DB query, 999 wait for result
```

**Cost**: ~1-5μs per duplicate request (very cheap). Prevents thundering herd.

---

## Part 11: Deadlock Detection and Prevention Strategies

### Detecting Deadlocks

Deadlocks are hard to debug. Common patterns:

```go
// DEADLOCK 1: Lock held too long
func process() {
    mu.Lock()
    defer mu.Unlock()

    // Waiting for external resource (network, channel)
    // While holding lock, another goroutine tries to acquire it
    result := blockingNetworkCall()  // Deadlock!
}

// DEADLOCK 2: Lock ordering
var mu1, mu2 sync.Mutex

func func1() {
    mu1.Lock()
    defer mu1.Unlock()
    // ...
    mu2.Lock()  // Acquires mu1, then mu2
    defer mu2.Unlock()
}

func func2() {
    mu2.Lock()
    defer mu2.Unlock()
    // ...
    mu1.Lock()  // Acquires mu2, then mu1 -> DEADLOCK!
    defer mu1.Unlock()
}

// DEADLOCK 3: Channel send under lock
func process() {
    mu.Lock()
    defer mu.Unlock()

    ch <- value  // If receiver waiting for lock, deadlock!
}

// Prevention:
// 1. Always acquire locks in same order (mu1, then mu2)
// 2. Never wait for I/O or channels under lock
// 3. Use context with timeouts to detect hangs
// 4. Add logging/tracing to find lock order violations
```

### Lock-Free vs Lock-Based Tradeoffs

```go
// Lock-based: Simple, correct, but contention risk
type Counter struct {
    mu    sync.Mutex
    count int64
}

func (c *Counter) Increment() {
    c.mu.Lock()
    c.count++
    c.mu.Unlock()
}

// Benchmark: ~200ns per operation under contention

// Lock-free (atomic): Faster under contention, but more complex
type CounterAtomic struct {
    count atomic.Int64
}

func (c *CounterAtomic) Increment() {
    c.count.Add(1)
}

// Benchmark: ~20ns per operation, no contention

// When to use each:
// - Mutex: Complex state (multiple fields), moderate contention
// - Atomic: Simple counters, high contention
// - sync.Map: Many readers, disjoint keys, few writers
```

---

## Interview Corner

### Q1: What are the differences between sync.Mutex and sync.RWMutex?

**Model Answer**:
- **Mutex**: Only one goroutine can hold the lock (reader or writer). Fair and simple.
- **RWMutex**: Multiple readers can hold the lock simultaneously, but writers are exclusive.

Use Mutex for balanced read/write workloads or small critical sections. Use RWMutex when read:write ratio is high (>10:1) and readers don't need consistency guarantees.

Trade-off: RWMutex is slower for writers and adds complexity. Only use if measurements show contention on readers.

### Q2: When should you use sync.Map?

**Model Answer**:
`sync.Map` is a lock-free map optimized for disjoint key access patterns. Use it when:
- Read-heavy workloads (many concurrent readers)
- Keys are mostly accessed by different goroutines (no contention on same key)
- You don't need atomic snapshots (Range is not atomic)

Don't use for:
- Frequent writes to the same keys
- Iterating over all entries frequently
- Needing strong consistency

Avoid: `sync.Map` with repeated writes to the same key causes performance degradation (dirty map promotions).

### Q3: Explain sync.Once and its use cases.

**Model Answer**:
`sync.Once` ensures code runs exactly once, even with concurrent calls. The second call waits for the first to complete, then returns immediately.

Use cases:
- Singleton initialization
- One-time setup (database pools, config loading)
- Lazy initialization

Cost: Very cheap (~10-50ns) on subsequent calls. Thread-safe without explicit locking.

Avoid: Complex error handling (Once doesn't capture errors; use a custom pattern for error propagation).

### Q4: How does the race detector work?

**Model Answer**:
The race detector instruments every memory operation (read/write) and tracks which goroutine accessed what. If two goroutines access the same memory without synchronization, it reports a race.

Instrumenting adds 5-10x overhead and 2-3x memory usage, so only use in testing with `-race` flag.

Important: The race detector has **false negatives** (won't catch all races) and **no false positives** (every race reported is real).

Enable in CI: `go test -race ./...`

### Q5: Design a thread-safe cache with expiration.

**Model Answer**:
```go
type Cache struct {
    mu    sync.RWMutex
    data  map[string]*entry
}

type entry struct {
    value  interface{}
    expiry time.Time
}

func (c *Cache) Get(key string) (interface{}, bool) {
    c.mu.RLock()
    defer c.mu.RUnlock()

    e, exists := c.data[key]
    if !exists || time.Now().After(e.expiry) {
        return nil, false
    }

    return e.value, true
}

func (c *Cache) Set(key string, value interface{}, ttl time.Duration) {
    c.mu.Lock()
    defer c.mu.Unlock()

    c.data[key] = &entry{
        value:  value,
        expiry: time.Now().Add(ttl),
    }
}
```

### Q6: Compare lock-free vs lock-based synchronization in a high-contention scenario.

**Model Answer**:
Lock-free (atomic) operations win under high contention because they avoid context switching and lock acquisition overhead.

```go
// Lock-based: contention causes waiting
type MutexCounter struct {
    mu    sync.Mutex
    count int64
}
// Under 1000 concurrent increments: ~1-5μs per operation

// Lock-free: no waiting
type AtomicCounter struct {
    count atomic.Int64
}
// Under 1000 concurrent increments: ~20ns per operation (100x faster!)
```

Use atomic for simple operations (counters, flags). Use mutex for complex state requiring multiple field updates.

### Q7: What's the best way to initialize a singleton with error handling?

**Model Answer**:
`sync.Once` doesn't handle errors well. Use a custom pattern:

```go
type Singleton struct {
    db  *sql.DB
    err error
    mu  sync.Once
}

func (s *Singleton) GetDB() (*sql.DB, error) {
    s.mu.Do(func() {
        s.db, s.err = sql.Open("postgres", connString)
    })
    return s.db, s.err
}

// Or use a custom struct:
type Config struct {
    value interface{}
    err   error
    done  chan struct{}
}

func (c *Config) Get() (interface{}, error) {
    <-c.done
    return c.value, c.err
}

func (c *Config) init() {
    defer close(c.done)
    c.value, c.err = loadConfig()
}
```

### Q8: Design a concurrent ticket counter with atomic operations that handles overbooking prevention.

**Model Answer**:
```go
type TicketCounter struct {
    available atomic.Int64
    sold      atomic.Int64
    maxTickets int64
}

func NewTicketCounter(max int64) *TicketCounter {
    return &TicketCounter{
        maxTickets: max,
    }
}

func (tc *TicketCounter) BuyTickets(count int64) bool {
    for {
        current := tc.available.Load()

        // Check if enough tickets
        if current < count {
            return false  // Not enough tickets
        }

        // Try atomic swap
        if tc.available.CompareAndSwap(current, current-count) {
            tc.sold.Add(count)
            return true
        }

        // CAS failed, retry (another goroutine got tickets first)
    }
}

func (tc *TicketCounter) Remaining() int64 {
    return tc.available.Load()
}

// Stress test
func TestConcurrentBooking(t *testing.T) {
    counter := NewTicketCounter(100)

    var wg sync.WaitGroup
    successCount := atomic.Int64{}

    for i := 0; i < 1000; i++ {
        wg.Add(1)
        go func() {
            defer wg.Done()
            if counter.BuyTickets(1) {
                successCount.Add(1)
            }
        }()
    }

    wg.Wait()

    // Only 100 should succeed
    if successCount.Load() != 100 {
        t.Errorf("sold %d; want 100", successCount.Load())
    }
}
```

Key insights:
- CAS loop retries when another goroutine wins
- atomic operations are lock-free and fast
- No mutex contention even with 1000 concurrent buyers

### Q9: What are the performance implications of RWMutex vs Mutex under different contention levels?

**Model Answer**:
```
Read:Write Ratio | Best Choice | Why
1:1             | Mutex       | RWMutex overhead > benefit
10:1            | RWMutex     | Many readers don't block each other
100:1           | RWMutex     | Clear winner; read throughput > 10x

Cost comparison (1000 concurrent ops):
Mutex:    50-100μs per op (all serialized)
RWMutex:  10-20μs per op (readers parallel, writers serialize)

BUT: RWMutex has fairness complexity:
- Writers must wait for all current readers
- New readers wait if writer waiting
- Can cause writer starvation under read-heavy load

Recommendation:
1. Measure before optimizing (use -race and benchmarks)
2. Start with Mutex (simple, predictable)
3. Switch to RWMutex only if profiling shows reader contention
4. Consider sync.Map for extreme read-heavy workloads with disjoint keys
```

**Model Answer**:
`sync.Once` doesn't handle errors well. Use a custom pattern:

```go
type Singleton struct {
    db  *sql.DB
    err error
    mu  sync.Once
}

func (s *Singleton) GetDB() (*sql.DB, error) {
    s.mu.Do(func() {
        s.db, s.err = sql.Open("postgres", connString)
    })
    return s.db, s.err
}

// Or use a custom struct:
type Config struct {
    value interface{}
    err   error
    done  chan struct{}
}

func (c *Config) Get() (interface{}, error) {
    <-c.done
    return c.value, c.err
}

func (c *Config) init() {
    defer close(c.done)
    c.value, c.err = loadConfig()
}
```

---

## Part 12: Benchmark: Lock Contention at Scale

Real-world performance data:

```go
// BenchmarkMutexContention benchmarks lock under increasing contention
func BenchmarkMutexContention(b *testing.B) {
    benchmarks := []struct {
        name        string
        goroutines  int
    }{
        {"1", 1},
        {"10", 10},
        {"100", 100},
        {"1000", 1000},
    }

    for _, bm := range benchmarks {
        b.Run(bm.name, func(b *testing.B) {
            var mu sync.Mutex
            var counter int

            b.ResetTimer()

            var wg sync.WaitGroup
            for g := 0; g < bm.goroutines; g++ {
                wg.Add(1)
                go func() {
                    defer wg.Done()
                    for i := 0; i < b.N/bm.goroutines; i++ {
                        mu.Lock()
                        counter++
                        mu.Unlock()
                    }
                }()
            }

            wg.Wait()
        })
    }
}

// Expected results (on modern CPU):
// 1 goroutine: ~50ns per increment
// 10 goroutines: ~200ns per increment (contention adds 4x)
// 100 goroutines: ~2μs per increment (heavy contention)
// 1000 goroutines: ~20μs per increment (severe contention)

// Compare with atomic:
// All levels: ~20ns per increment (no contention difference!)

// Takeaway: Switch to atomic for high-concurrency counters
```

---

## Tradeoffs and Best Practices

### Mutex vs Atomic
- **Mutex**: Protects complex state, but adds contention
- **Atomic**: Only for simple values (counters, flags), lock-free
- Atomic is 5-50x faster for simple cases, but doesn't compose

### Lock Granularity
- **Too coarse**: Contention on high-concurrency paths
- **Too fine**: Overhead of frequent lock/unlock, deadlock risk
- Balance: Lock only what's necessary, keep critical sections short

### RWMutex Efficiency
- RWMutex has overhead (fairness tracking) even without contention
- Only use if measurements show reader contention
- Many experts prefer channels for coordination

### Initialization Patterns
- `sync.Once`: Simple, efficient, safe
- Double-check locking: Error-prone, avoid
- Interface injection: Simplest for testing and flexibility

---

## Exercise

Build a **user presence system** with:
1. Concurrent online/offline status updates
2. Read-heavy presence checks
3. Batch operations (get all online users)
4. Proper synchronization (no races, no deadlocks)
5. Performance optimization (use sync.RWMutex or sync.Map)

Requirements:
- Must pass `go test -race`
- Must handle 1000+ concurrent goroutines
- Batch reads must not block individual updates
- Must support graceful shutdown

Bonus: Add presence expiration (auto-offline after 5 minutes of no updates) with a cleanup goroutine.

