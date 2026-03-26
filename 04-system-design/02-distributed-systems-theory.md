# Distributed Systems Theory: Foundations for Production Systems

## Table of Contents
1. [CAP Theorem](#cap-theorem)
2. [ACID vs BASE](#acid-vs-base)
3. [Consensus Protocols](#consensus-protocols)
4. [Distributed Clocks](#distributed-clocks)
5. [Conflict Resolution](#conflict-resolution)
6. [Consistent Hashing](#consistent-hashing)
7. [Gossip Protocols](#gossip-protocols)
8. [Distributed Locking](#distributed-locking)
9. [MVCC](#mvcc)
10. [Quorum Reads/Writes](#quorum-readsrites)
11. [Consistency Models](#consistency-models)
12. [Bloom Filters](#bloom-filters)
13. [Production Relevance](#production-relevance)
14. [Interview Questions](#interview-questions)

---

## CAP Theorem

The CAP theorem states: In a distributed system, you can guarantee at most TWO of the following THREE properties:

- **Consistency (C):** All nodes see the same data at the same time
- **Availability (A):** Every request receives a response (success or failure)
- **Partition Tolerance (P):** System continues operating despite network partitions

### The Misunderstanding

Most engineers misunderstand CAP. They think:
- "CP systems: consistent but unavailable"
- "AP systems: available but inconsistent"

**Reality:** The partition (P) is not a choice. In a distributed system, network partitions WILL happen. The question is: when they do, what do you sacrifice?

- **CP (Consistency over Availability):** When partition occurs, stop accepting writes to prevent inconsistency. System unavailable but data is consistent.
  - Example: Traditional banking (transactions must be consistent)

- **AP (Availability over Consistency):** When partition occurs, continue accepting writes. Nodes may diverge. Later reconcile.
  - Example: Social media (a like may appear inconsistent for seconds)

### PACELC Extension

Eric Brewer extended CAP to PACELC:
- **If there's a Partition:** Consistency OR Availability
- **Else (no partition):** Latency OR Consistency

"Else" is where you spend most of your time. Even without partitions, you choose: trade latency for consistency?

```
System Design Decision Tree:

Network Partition Occurs?
├─ Yes (P): Choose C or A
│   ├─ CP: Stop writes, wait for network → Data consistent, slow/unavailable
│   └─ AP: Continue writes, sync later → Available, temporarily inconsistent
│
└─ No (normal operation): Choose L or C
    ├─ High Latency acceptable: Choose C (wait for quorum writes, strong consistency)
    │   Example: 500ms write latency, guaranteed consistency
    │
    └─ Low Latency required: Choose eventual consistency (return immediately)
        Example: <10ms write latency, sync later
```

### Movie Booking Example

```
CAP choices for different components:

1. Booking creation (write seat reservation):
   - Must be Consistent: overselling is catastrophic
   - CP choice: if datacenter partition, stop accepting bookings
   - Trade: availability for correctness

2. Seat availability cache:
   - Can tolerate eventual consistency: users refresh page to see latest
   - AP choice: continue serving cached availability during partition
   - Trade: consistency for availability

3. User profile (name, email):
   - Can tolerate eventual consistency: profile changes slowly
   - AP choice: propagate changes eventually, serve stale reads immediately
   - Trade: consistency for latency

4. Payment processing:
   - Must be Consistent: double-charging is worse than downtime
   - CP choice: synchronous payment verification, fail fast on network issues
   - Trade: availability for correctness
```

---

## ACID vs BASE

Two models for data consistency.

### ACID (Traditional Databases)

**Atomicity:** Transaction all-or-nothing
```sql
BEGIN;
  INSERT INTO bookings VALUES (123, show_id, user_id);
  UPDATE seat_inventory SET count = count - 1;
COMMIT;  -- Both or neither happen
```

**Consistency:** Data in valid state before and after
```
Invariant: seat_inventory = number of available seats
Before: inventory=100, bookings=0
After: inventory=99, bookings=1
Always true.
```

**Isolation:** Concurrent transactions don't interfere
```sql
Transaction A: Decrement inventory
Transaction B: Decrement inventory
Result: inventory decremented twice (not once)
Isolation prevents this
```

**Durability:** Committed data persists despite crashes
```
Commit successful → power goes out → data still there after restart
```

**Tradeoff:** ACID guarantees are expensive (distributed locking, synchronous I/O)

### BASE (Eventual Consistency)

**Basically Available:** System responds even if some data is inconsistent
```
"Yes, seats available (from 1s-old cache)"
Reality: may be outdated, but responds immediately
```

**Soft state:** Data in temporary states (replicating, caching)
```
User updates profile
→ Immediately written to local cache (soft state)
→ Asynchronously synced to database
→ Eventually replicated to other datacenters
```

**Eventually Consistent:** Given time, all copies converge to same state
```
User books seat:
Time 0:   Recorded in NYC datacenter
Time 100ms: Replicated to London
Time 150ms: Replicated to Tokyo
Eventually all agree on same booking
```

**Tradeoff:** BASE is fast and available, but requires eventual reconciliation

### Real-World Hybrid

```
Movie Booking System:

Booking creation (critical path): ACID
├─ Atomically decrement inventory
├─ Atomically insert booking record
└─ Synchronous write to primary DB

Seat availability (read path): BASE
├─ Return from cache (potentially stale)
├─ Background job updates cache every 5 seconds
└─ If stale data causes issues, users refresh manually

Booking confirmation: ACID
├─ Email confirmation written synchronously
└─ Rollback entire booking if email fails

Booking analytics: BASE
├─ Asynchronously update analytics datastore
├─ Acceptable to be 1-2 minutes behind
└─ Eventual consistency across analytics replicas
```

**Decision framework:**
- Booking itself: ACID (money/inventory involved)
- User communication: Eventually consistent (Email is async anyway)
- Reporting/Analytics: BASE (stale data acceptable)
- Inventory display: BASE with refresh button (users understand cache)

---

## Consensus Protocols

Consensus: How do distributed nodes agree on a decision despite failures?

### Raft (Easier to Understand)

Raft divides time into terms. Each term has at most one leader.

**States:**
```
Node can be:
├─ Follower: listens to leader
├─ Candidate: trying to become leader
└─ Leader: commands all followers
```

**Leader Election:**

```
Initial state: Node A, B, C all followers

Timeout (no leader): Node A becomes candidate
├─ Increments term: term=1
├─ Votes for itself
├─ Sends RequestVote RPC to B, C
│
B and C receive RequestVote:
├─ Check if A's term >= their term: YES
├─ Check if A's log is >= their log: YES
├─ Vote for A, update term to 1
│
A receives votes from B and C (majority of 3):
├─ Becomes leader
├─ Sends heartbeat to all followers
│   Heartbeat: "I'm alive, you don't need to vote for someone else"
```

**Log Replication (Normal Operation):**

```
Client: "Book seat 123"
         ↓
       Leader (A)
         ├─ Append to own log: (term=1, index=5, "Book seat 123")
         ├─ Send AppendEntries RPC to B, C
         ↓
       Followers B, C
         ├─ Append to own log
         ├─ Send success response
         ↓
       Leader A receives success from majority
         ├─ Applies to state machine: executes booking
         ├─ Returns to client: "Success"
         ├─ Sends "commit index" to followers
         ↓
       Followers B, C
         ├─ Receive commit index
         ├─ Apply entries up to commit index
         ↓
    All three: booking applied
    All three: same state
```

**Safety:** Raft guarantees
```
1. Election safety: At most one leader per term
2. Log matching: If two logs have entry at same index, all prior entries identical
3. Leader completeness: Leader's log contains all committed entries
4. State machine safety: If entry applied to state machine, no other node will apply different entry at that index
```

### Paxos (Harder but More Powerful)

Paxos is harder to understand but more flexible than Raft.

**Three roles:**
- **Proposer:** Proposes a value
- **Acceptor:** Votes on proposals (learns accepted value)
- **Learner:** Learns accepted value

**Two phases:**

Phase 1 (Prepare):
```
Proposer: "Will anyone promise to not accept proposals with lower number than N?"
Acceptors: "OK, I promise. Here's the highest-numbered proposal I've seen."

This prevents split-brain: only one proposer can proceed.
```

Phase 2 (Accept):
```
Proposer: "Accept value V for proposal N"
Acceptors: "OK, accepted. Learned value is V."

Once a majority accepts, value is committed.
```

**Paxos is messy:**
```
Multiple proposers can be competing
Prepare requests can fail
Accept requests can fail
Need to restart if conflicts

Raft is simpler: elect ONE leader, leader handles all proposals
```

### Movie Booking Use Case

```
Consensus needed: Coordinate seat allocation across 3 datacenters

Using Raft:
Leader (DatacenterA): All seat bookings go here
├─ Replicate to DatacenterB, DatacenterC
├─ Wait for acknowledgment from majority (A + B or A + C)
├─ Return to user: "Seat booked"
│
DatacenterB temporarily down:
├─ Leader sends heartbeat to A, C
├─ Majority acknowledged (A + C)
├─ Continue normally
├─ When B comes back: catch up from logs
│
Majority (A+B) down, only C alive:
├─ C can't get majority vote
├─ C steps down as leader (can't make decisions)
├─ No booking acceptance
├─ Trade: Availability for safety
```

---

## Distributed Clocks

In distributed systems, wall-clock time isn't reliable. Nodes have clock skew (different times).

### Lamport Timestamps

Simple counter that increases with every event.

```go
type LamportTimestamp int

// Node A:
a.clock = 1
SendMessage(nodeB, "book seat")
a.clock = 2

// Node B receives with timestamp 1:
b.clock = max(b.clock, 1) + 1 = 2

// Node B local event:
b.clock = 3

// Ordering property:
Event A happened before Event B → A.timestamp < B.timestamp
Proof: Lamport clock only increases
```

**Limitation:** Can't distinguish concurrent events.

```
Event A: timestamp=5
Event B: timestamp=5
Are they concurrent? Possibly.
Did A happen before B? Can't tell.
```

### Vector Clocks

Each node tracks timestamp for every other node.

```go
type VectorClock map[NodeID]int

// Node A: [A=1, B=0, C=0]
// Node B: [A=0, B=1, C=0]
// Node C: [A=0, B=0, C=1]

// A sends to B:
A increments own: [A=2, B=0, C=0]
Sends to B with this timestamp

// B receives [A=2, B=0, C=0]:
B updates: [A=2, B=1, C=0]  // max per component
Now B knows A is at timestamp 2

// Ordering:
VC1 < VC2 if VC1[i] <= VC2[i] for all i AND VC1 != VC2
VC1 || VC2 (concurrent) if neither < nor >
```

**Concurrent events:**
```
Node A: [A=2, B=1, C=0]  "User booked seat"
Node B: [A=1, B=2, C=0]  "Seat inventory checked"

Neither A < B nor B < A → They're concurrent!
No causal ordering.
```

**Limitation:** Vector grows with number of nodes (scales poorly to 1000s of nodes)

### Hybrid Logical Clocks (HLC)

Combines wall-clock time with logical counters.

```go
type HLC struct {
    physical int64  // Wall-clock time (ms)
    logical  int    // Logical counter
}

// Node A at time 1000ms:
a.hlc = HLC{1000, 0}

// Node B at time 999ms (slightly behind):
b.hlc = HLC{999, 0}

// A sends to B:
A increments: HLC{1000, 1}

// B receives:
B's physical is 999 < received.physical 1000
So: HLC{1000, 1}  // Accept A's physical time!
Then: HLC{1000, 2}  // B continues from there

// Result: B's clock is adjusted towards A's, but not instantly
```

**Advantages:**
- Works like wall-clock time (readable)
- Doesn't grow with number of nodes
- Consistent with causality

### Movie Booking Example

```
Using Vector Clocks for ordering:

EventA: User books seat
  [Booking Service=1, Inventory Service=0, Payment Service=0]

EventB: Inventory decremented
  Received from Booking Service: [1, 0, 0]
  Own increment: [1, 1, 0]

EventC: Payment processed
  Received from Payment Service: [0, 0, 1]
  Know about Booking: [1, 1, 0]
  Merge: [1, 1, 1]

Concurrent events:
  EventX: Cache invalidated [1, 0, 0]
  EventY: Reservation extended [0, 1, 0]

  Neither causally ordered
  Need application-level conflict resolution
```

---

## Conflict Resolution

When multiple replicas diverge (due to network partition or concurrent writes), how do you reconcile?

### Last-Writer-Wins (LWW)

Simplest: take the most recent write by wall-clock time.

```
Replica A: user_profile.name = "John" (time 1000)
Replica B: user_profile.name = "Jane" (time 1001)

Conflict: same field, different values

LWW: "Jane" wins (time 1001 > 1000)

Problem: what if clock is skewed?
Replica A's clock fast: could overwrite legitimate update
```

**When to use:**
- Caches (ok to lose old data)
- Session data (ephemeral)
- Analytics (approximate counts ok)

**When NOT to use:**
- Inventory (overselling)
- Payments (double-charging)
- Bookings (double-booking)

### CRDTs (Conflict-free Replicated Data Types)

Data structures designed for conflict-free merging.

**G-Counter (Grow-only Counter):**
```
Each node has own counter: {A: 5, B: 3, C: 7}
Total = 5 + 3 + 7 = 15

Node A increments: {A: 6, B: 3, C: 7}
Node B increments: {A: 5, B: 4, C: 7}

Concurrent: both see total = 15
Each sees their increment immediately: A sees 16, B sees 15

Later merge: {A: 6, B: 4, C: 7} → total = 17
Both increments preserved! No data loss.

Cons: Can only increment (no decrement)
```

**LWW-Register (Last-Writer-Wins Register):**
```
Value: "John" (time 1000, node A)

Concurrent write: "Jane" (time 1001, node B)

Merge: Compare (time, nodeID):
  (1000, A) < (1001, B) → take "Jane"

Deterministic: (1001, B) > (1000, A) because 1001 > 1000
```

**Multi-Value Register (OR-Set / Observed-Remove Set):**
```
Add a movie to favorites: movie:123 @ (time=1000, node=A)
Concurrently remove: movie:123 @ (time=1001, node=B)

Instead of LWW, keep both:
State = {added: {(1000, A)}, removed: {(1001, B)}}
Current value = added - removed = {(1000, A)} - {(1001, B)} = EMPTY

If add comes later:
movie:123 @ (time=1002, node=A)
State = {added: {(1000, A), (1002, A)}, removed: {(1001, B)}}
Current value = PRESENT (1002 > 1001)
```

### Application-Level Conflict Resolution

For business logic, sometimes you need custom logic.

```go
// Two competing bookings for same seat
booking1 := Booking{SeatID: 123, UserID: 1, Time: 1000}
booking2 := Booking{SeatID: 123, UserID: 2, Time: 1001}

// LWW: booking2 wins (more recent)
// But actually: if booking1 already paid, we should keep it!

func ResolveSeatConflict(b1, b2 *Booking) (*Booking, error) {
    // Rule 1: Paid booking always wins
    if b1.Status == "paid" && b2.Status != "paid" {
        return b1, nil
    }
    if b2.Status == "paid" && b1.Status != "paid" {
        return b2, nil
    }

    // Rule 2: Both paid or both unpaid → more recent wins
    if b1.Time > b2.Time {
        return b1, nil
    } else if b2.Time > b1.Time {
        return b2, nil
    }

    // Rule 3: Same time → error, manual intervention
    return nil, fmt.Errorf("unresolvable conflict: both bookings at same time")
}
```

---

## Consistent Hashing

Already covered in Scaling Patterns, but critical enough to repeat.

When you have N servers and need to distribute keys:

**Naive: hash(key) % N**
```
Add a server (N → N+1):
All keys rehash!
Almost all keys move to different servers
Massive data movement

hash(key) % 5 = 2 → key goes to server 2
hash(key) % 6 = 2 or 5 → key might move!
```

**Consistent Hashing: hash values on ring [0, 2^32)**
```
Place servers on ring:
Server A @ position 100,000
Server B @ position 200,000
Server C @ position 50,000

Ring: 0 -------- 50K (C) -------- 100K (A) -------- 200K (B) -------- 2^32

Key hashing:
hash(key1) = 75,000 → between C and A → goes to A
hash(key2) = 30,000 → between B and C → goes to C
hash(key3) = 150,000 → between A and B → goes to B

Add Server D @ 160,000:
Only keys between 100K-160K move from B to D
~25% of B's keys, not all!
```

**Virtual Nodes:**
```
Real servers: A, B, C (3 total)
Virtual nodes: each server gets 160 vnodes
Total vnodes: 480

Spread on ring evenly:
A: vnode_A_0, vnode_A_1, ... vnode_A_159
B: vnode_B_0, vnode_B_1, ... vnode_B_159
C: vnode_C_0, vnode_C_1, ... vnode_C_159

Add Server D:
D takes vnode_X_32 to vnode_X_159 from each server
Only ~67 vnodes per server move (1/3 of D's vnodes each)
~25% of data moves (better than 50% without vnodes)
```

---

## Gossip Protocols

Decentralized information spreading. Node A tells a few friends, they tell a few friends, etc.

### Anti-Entropy

Each node periodically syncs state with random peers.

```
Time 0:
Node A has: metadata version 100
Node B has: metadata version 95
Node C has: metadata version 95

Time T1: A talks to B
B sees A has version 100 → B updates to 100

Time T2: B talks to C
C sees B has version 100 → C updates to 100

Time T3: C talks to A
A has 100, C has 100 → no change

After 3 rounds: All synchronized
Convergence time: O(log N)
```

### Rumor Mongering

Node spreads news (change) to random peers. Each peer either accepts or is "immune" (already knows).

```
Change: "Server D added"

Node A: "Hey B, Server D was added"
B: "Oh thanks, I didn't know!"
B: "Hey C, Server D was added"
C: "Oh thanks, I didn't know!"
C: "Hey A, Server D was added"
A: "Yep, already knew" (immune)

Within seconds, all nodes aware.
Exponential spread: 1 → 2 → 4 → 8 → 16 → ...
```

### SWIM (Scalable Weakly-Consistent Infection-Style Protocol)

Combines gossip with failure detection.

```
Failure detection:

Node A: "Hey B, you alive?"
B: silence for 1 second (dead?)

Node A asks: "Hey C, is B alive?"
C: "No, haven't heard from B"

A declares B dead, spreads via gossip
"Hey D, B is dead"
D: "Got it, I'll tell others"

Result: Network converges on "B is dead"
Probabilistic: might take a few seconds, but eventually consistent
```

### Movie Booking Gossip

```
Event: "New movie added"

EventStore publishes via gossip:
├─ Notification Service hears (10ms)
├─ Cache Service hears (15ms)
├─ Reporting Service hears (25ms)
├─ Mobile Service hears (30ms)

All learn within ~100ms without central coordinator
If a service is offline, catches up when it rejoins
Self-healing: no manual intervention needed
```

---

## Distributed Locking

Ensure only one process holds a lock at a time.

### Redis Redlock

Use Redis to coordinate locks.

```go
type RedisLock struct {
    key        string
    token      string    // Unique identifier
    ttl        time.Duration
}

func (rl *RedisLock) Acquire(ctx context.Context) error {
    // SET key token NX EX ttl
    // NX: only set if key doesn't exist
    // EX: expire after ttl
    ok := redis.SetNX(ctx, rl.key, rl.token, rl.ttl)
    return ok
}

func (rl *RedisLock) Release(ctx context.Context) error {
    // Only delete if token matches (prevent deleting others' locks)
    script := `
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
    `
    return redis.Eval(ctx, script, rl.key, rl.token)
}
```

**Benefits:**
- Simple
- Fast (in-memory)
- Works for non-critical locks

**Problems (Martin Kleppmann Critique):**

```
Scenario 1: Clock skew
├─ Lock set to expire in 10 seconds
├─ Owner's clock jumps forward 15 seconds
├─ Lock expires (owner thinks still locked!)
├─ Another process acquires lock
├─ Disaster: two processes think they hold lock

Scenario 2: GC pause
├─ Process acquires lock: token=ABC, ttl=10s
├─ Process has GC pause: 15 seconds
├─ Lock expires while process is paused
├─ Another process acquires lock
├─ GC resumes, process still thinks it holds lock
├─ Disaster: two processes operating on locked resource

Scenario 3: Network partition
├─ Process holds lock on Redis primary
├─ Network partition: process can't reach Redis
├─ Process loses lock, doesn't realize it
├─ Another process (able to reach Redis) acquires lock
├─ Disaster: two processes think they own resource
```

**Kleppmann conclusion:** Redlock insufficient for critical sections. Need:
- Fencing tokens: server tags each operation with token version
- Multiple Redis instances: majority consensus
- Or use ZooKeeper/etcd (proper consensus)

### ZooKeeper Locks

ZooKeeper uses Raft consensus.

```
Lock = ephemeral sequential node in ZooKeeper

Process 1:
├─ Creates /locks/booking_1000
├─ Watches for deletion
├─ If deleted, retries

Process 2:
├─ Tries to create /locks/booking_1000
├─ Already exists, watches it
├─ Waits for Process 1 to finish
├─ Sees deletion, acquires lock

Safe because:
├─ Consensus: all ZK replicas agree
├─ Fencing: lock version prevents old process from interfering
└─ Atomic: operations all-or-nothing
```

### etcd Locks

Similar to ZooKeeper but simpler, focused on configuration.

```go
// etcd lock

// Acquire
lease := etcd.Grant(ctx, 10)  // 10-second TTL
err := etcd.Put(ctx, "/locks/seat_123", "owner_token",
    clientv3.WithLease(lease.ID))

// Hold while doing work
// If process dies: TTL expires → lock released
// If process alive: renew TTL
etcd.KeepAlive(ctx, lease.ID)

// Release
etcd.Revoke(ctx, lease.ID)  // Delete key
```

### Movie Booking Lock Choice

```
Scenario 1: Seat lock during booking (critical)
├─ Use etcd or ZooKeeper (consensus)
├─ Can't use Redis Redlock (catastrophic if two users double-book)
├─ Acceptable downtime: yes, better safe than sorry

Scenario 2: Cache refresh lock (non-critical)
├─ Use Redis Redlock (fast)
├─ If lock fails: worst case is duplicate refresh
├─ Acceptable loss: yes

Scenario 3: Session lock (moderate)
├─ Use Redis Redlock with shorter TTL (5 seconds)
├─ If fails: user re-authenticates
├─ Acceptable: yes
```

---

## MVCC (Multi-Version Concurrency Control)

How do databases avoid locking readers and writers?

### PostgreSQL MVCC Implementation

Each row has:
- **xmin:** transaction ID that inserted this version
- **xmax:** transaction ID that deleted this version

```sql
-- Initial state
Transaction 1: INSERT INTO users (id=1, name="John")
  Inserts version with xmin=1, xmax=NULL

-- Later
Transaction 2: UPDATE users SET name="Jane" WHERE id=1
  Marks old version xmax=2
  Inserts new version with xmin=2, xmax=NULL

-- Visibility rules
Transaction 3 (id=3) queries:
  Can see version with xmin=1, xmax=NULL?
    ├─ xmin (1) < my xid (3)? Yes
    ├─ xmax is NULL or >= my xid? Yes (NULL)
    └─ VISIBLE

Transaction 1 (id=1) queries:
  Can see version with xmin=2, xmax=NULL?
    ├─ xmin (2) < my xid (1)? No (2 > 1)
    └─ NOT VISIBLE

Reader sees consistent snapshot: doesn't need locks!
```

### Visibility Map and Vacuum

As transaction IDs get large, visibility becomes ambiguous.

```
Transaction IDs: 0 to 2^32-1 (4 billion max)
After 4 billion transactions, IDs wrap around

Old version: xmin=100
New transaction: xid=50 (wrapped around)
Is 50 < 100? YES!
But actually: old transaction was way before

Solution: Vacuum process
├─ Rewrites tuples, updates xmin/xmax
├─ Removes dead versions
├─ Freezes old transactions (marks as committed)
└─ Prevents ID wraparound issues
```

### MVCC Benefits

**Readers don't block writers:**
```
Writer: Hold lock, write row 10 versions
Reader: Read version 5 (or whatever's appropriate)
No conflict! Reader sees consistent snapshot
```

**Writes don't block readers:**
```
Reader: Scanning 1M rows
Writer: Updates rows 500-600
Reader: Continues, sees old versions of 500-600
Later queries see new versions
```

**Downside: Disk space (dead versions accumulate)**
```
Update same row 1M times:
Without MVCC: 1 version, 1M row locks
With MVCC: 1M versions, ~1M * 100 bytes = 100MB
Vacuum cleans up, but slower than in-place updates
```

---

## Quorum Reads/Writes

Trade consistency for availability/latency via quorums.

### Write Quorum

To write, require acknowledgment from majority of replicas.

```
3 replicas: A, B, C
Quorum = 2

Write "seat booked":
├─ Send to A: success
├─ Send to B: success (2/3, quorum met!)
├─ Send to C: (doesn't matter)
└─ Return to client: written

Guarantees:
├─ Can lose one replica (still have 2 with data)
└─ Any two replicas overlap (at least one has new write)
```

### Read Quorum

To read, require answer from majority of replicas.

```
Write quorum W = 2, Read quorum R = 2

Write received by: A, B
Can't read from C only (outdated)
Must read from 2+ replicas:
├─ Read from A, B: guaranteed to see new data
├─ Read from B, C: one is new (B), one is old (C), take newer
└─ Read from A, C: one is new (A), one is old (C), take newer
```

### R + W > N

To guarantee strong consistency:

```
N = total replicas
W = write quorum
R = read quorum

If W + R > N:
  Any read quorum overlaps with any write quorum
  Read always sees latest write

Example:
N = 3, W = 2, R = 2
W + R = 4 > 3 ✓

N = 5, W = 3, R = 3
W + R = 6 > 5 ✓

N = 5, W = 2, R = 2
W + R = 4 < 5 ✗ (Not guaranteed!)
```

### Movie Booking Quorum

```
3 replicas (us, backup, disaster)
Booking is critical: use W=2, R=2

Write "booking confirmed":
├─ Must replicate to 2 replicas (can lose 1)
├─ Read always sees confirmed bookings
└─ Safe

Seat availability (eventual consistency ok):
├─ Write W=1 (fast)
├─ Read R=1 (fast)
├─ Might see stale availability
├─ Users refresh to see latest
```

---

## Consistency Models

### Linearizability

Operations appear to happen instantly, in order.

```
Time: |--A write x=1--|  |--B read x--|  |--C read x--|
      └ After A finishes, B and C see x=1

Always see most recent write, not old values
```

**Cost:** Requires synchronous replication or quorum writes
**Use:** Critical operations (payments, inventory)

### Serializability

Transactions appear to happen one-at-a-time.

```
Transaction A: read x, write y
Transaction B: read y, write x

Serializable: either A then B, or B then A (not interleaved)
Not linearizable: results might not reflect wall-clock time
```

**Cost:** Database-level transaction management
**Use:** Complex multi-statement transactions

### Causal Consistency

If A happens before B (causal), all nodes see A then B.

```
User posts comment (event A)
Friend likes comment (event B, depends on A)

All nodes:
├─ See post before like
├─ Never see like without post
└─ But timing might vary per replica
```

**Cost:** Track causal dependencies (vector clocks)
**Use:** Social media, messaging (eventual consistency is ok)

### Eventual Consistency

Eventually, all replicas converge.

```
User updates profile:
├─ Replica 1: immediate
├─ Replica 2: 100ms later
├─ Replica 3: 200ms later
Eventually all match
```

**Cost:** Minimal (asynchronous replication)
**Use:** Caches, sessions, analytics

---

## Bloom Filters

Probabilistic data structure for membership testing.

### How It Works

```
Bloom filter: array of N bits (initially 0)
Hash functions: h1, h2, ..., hk

Insert element X:
├─ Compute h1(X) mod N = position 5
├─ Compute h2(X) mod N = position 12
├─ Compute h3(X) mod N = position 18
├─ Set bits[5] = bits[12] = bits[18] = 1

Query: Is X in filter?
├─ Compute h1(X) mod N = 5, h2(X) mod N = 12, h3(X) mod N = 18
├─ Check bits[5], bits[12], bits[18]
├─ If all 1: probably yes (false positive possible!)
├─ If any 0: definitely no
```

### False Positives

```
Bits: [0, 1, 0, 1, 1, 0, 1, 1, 0, 1, ...]

Check X:
├─ h1(X) = 3 → bits[3] = 1 ✓
├─ h2(X) = 5 → bits[5] = 1 ✓
├─ h3(X) = 7 → bits[7] = 1 ✓
└─ Result: "probably in set"

But what if these 1s are from different elements?
Result: false positive (X not actually in set)

No false negatives: if any bit is 0 → definitely not in set
```

### False Positive Rate

```
FPR = (1 - e^(-kn/m))^k

m = filter size (bits)
n = number of inserted elements
k = number of hash functions

Typical: m = 10n, k = 7 → FPR ≈ 0.8%
```

### Use Cases

**Cache lookups:**
```
"Is user 123 in cache?"
├─ Bloom filter says no → don't look in cache
├─ Bloom filter says yes → look in cache
└─ Saves disk I/O (even false positives are cheap)
```

**Database lookups:**
```
"Does row with key=X exist?"
├─ Bloom filter says no → definitely not (don't query)
├─ Bloom filter says yes → query database
└─ Reduces database queries by 90%
```

**Duplicate detection:**
```
Process emails:
├─ Bloom filter: "Have I seen this email ID?"
├─ No → process it, add to filter
├─ Yes → probably a duplicate, skip
└─ Rare false positives acceptable
```

**Movie Booking use case:**
```
"Is user already booked for this show?"
├─ Fast check: Bloom filter has (user_id, show_id)
├─ If no: definitely not booked
├─ If yes: query database to confirm (1% false positive)
└─ Saves N database queries for N users checking
```

---

## Production Relevance

What actually matters when building real systems?

### You'll definitely encounter:

1. **Eventual consistency:** Replication lags are real
2. **Network partitions:** Someone's datacenter loses connection
3. **Distributed locking:** Coordinating concurrent writes
4. **Quorum reads/writes:** Balancing consistency and availability
5. **MVCC:** PostgreSQL, MySQL use it invisibly
6. **Replication lag:** Replicas aren't instant
7. **Consensus:** Electing leaders (Kubernetes uses Raft)

### You probably won't:

- Implement Paxos (use existing systems)
- Implement Raft from scratch (use etcd, Consul)
- Manage vector clocks manually (databases handle it)
- Write MVCC code (databases provide it)

### What to focus on:

1. **Understand CAP:** Know your tradeoffs
2. **Know consistency models:** Choose appropriate one per component
3. **Understand replication:** Lag, failover, recovery
4. **Understand locking:** When to use strong vs weak locks
5. **Know your tools:** etcd, Redis, ZooKeeper, Kafka

---

## Interview Questions

1. **Explain the CAP theorem and PACELC. How do they apply to a movie booking system?**

   Model answer:
   - CAP: In partition, choose consistency (risk overselling) or availability (risk inconsistency)
   - PACELC: Without partition, choose between latency (fast) and consistency (slower, quorum writes)

   Movie booking:
   - Bookings: CP or latency sacrifice (quorum writes, sync, ~500ms)
   - Seat availability: AP or latency (async cache, stale ok)
   - User profiles: AP (eventual consistency)

2. **Design a distributed lock for booking seats in a movie theater. What are the failure modes?**

   Model answer:
   - Use Redis with TTL for non-critical (duplicate cache refresh is ok)
   - Use etcd for critical (overselling unacceptable)

   Failure modes:
   - Process dies: TTL expires, lock released
   - Clock skew: lock expires too early/late (mitigate with short TTL)
   - Network partition: process loses lock without knowing (use lease renewal)
   - Lock starvation: many contenders, some never get lock (fair queuing)

3. **Your database uses MVCC. A transaction is scanning 1M rows for reporting, and a writer is updating 1M rows. How does this work without locking?**

   Model answer:
   - Reader: takes snapshot at transaction start, sees versions as of that time
   - Writer: creates new versions, marks old versions deleted (xmin/xmax)
   - No locking: reader doesn't block writer, writer doesn't block reader

   Downside: Dead versions accumulate (1M updates = 1M versions)
   Solution: Vacuum reclaims space

4. **Compare quorum reads/writes with strong consistency (W=all, R=1). Why use quorum at all?**

   Model answer:
   - W=all: every write waits for all replicas (slow, unavailable if any replica down)
   - W=N/2 + 1: write waits for majority (faster, tolerate one replica down)
   - R + W > N: still strong consistency, more available

   Trade-off: slightly higher latency (quorum coordination) for availability

5. **Your system uses gossip protocols for spreading updates. A critical update (major bug fix) isn't spreading. Why? How to debug?**

   Model answer:
   - Gossip is probabilistic: nodes spread to random peers
   - Rare events might not reach all nodes quickly
   - Or: node is down (gossip doesn't reach it while down, catches up when back)

   Debug:
   - Check node health (is target node alive?)
   - Monitor gossip ring (who's talking to whom?)
   - Increase gossip frequency (for critical updates)
   - Use direct push (don't rely on gossip for critical updates)

6. **Explain Bloom filters and when you'd use them in a movie booking system.**

   Model answer:
   - Bloom filter: probability "is element in set?"
   - Fast checks (O(k) hash lookups) vs slow database queries

   Use cases:
   - "Is user already booked for this show?" → Bloom filter + DB confirms
   - "Has this credit card been used?" → Bloom filter prevents duplicate processing
   - Reduces ~90% of database queries

   Trade-off: rare false positives (1%, mitigated by DB confirmation)

