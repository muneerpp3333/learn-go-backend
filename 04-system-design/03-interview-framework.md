# System Design Interview Framework: Master Class for $200K+ Roles

## Table of Contents
1. [The 45-Minute Interview Structure](#the-45-minute-interview-structure)
2. [Phase 1: Requirements (5 min)](#phase-1-requirements-5-min)
3. [Phase 2: High-Level Design (10 min)](#phase-2-high-level-design-10-min)
4. [Phase 3: Deep Dive (20 min)](#phase-3-deep-dive-20-min)
5. [Phase 4: Wrap-up (10 min)](#phase-4-wrap-up-10-min)
6. [Back-of-Envelope Estimation](#back-of-envelope-estimation)
7. [Full Worked Example: Movie Booking System](#full-worked-example-movie-booking-system)
8. [Full Worked Example: WhatsApp Messaging System](#full-worked-example-whatsapp-messaging-system)
9. [Common Questions with Approach](#common-questions-with-approach)
10. [Red Flags and How to Avoid Them](#red-flags-and-how-to-avoid-them)
11. [Interview Meta-Questions](#interview-meta-questions)

---

## The 45-Minute Interview Structure

A typical system design interview lasts 45-60 minutes. Use this breakdown:

### Minute-by-Minute Breakdown

**0-5 min: Requirements & Estimation**
- Clarify what "movie booking system" means
- Gather functional requirements (what should it do?)
- Gather non-functional requirements (scale, latency, consistency)
- Do back-of-envelope math (users, QPS, storage, bandwidth)

**5-15 min: High-Level Design**
- Draw boxes and arrows (services, databases, caches)
- Identify core components and data flow
- Show you think about scale and tradeoffs
- Get feedback from interviewer ("does this direction make sense?")

**15-35 min: Deep Dive (pick 2-3 components)**
- Go deep on the most interesting/hardest part
- Show knowledge of tradeoffs, failure modes, production concerns
- This is where senior-level thinking shines
- Ask clarifying questions ("should we prioritize latency or consistency here?")

**35-45 min: Wrap-up**
- Identify bottlenecks and how to handle them
- Discuss monitoring, alerting, operational aspects
- Future extensions (if time permits)
- Graceful shutdown, handling graceful degradation

---

## Phase 1: Requirements (5 min)

### Functional Requirements

What should the system actually do?

**For movie booking:**
```
- Users can view movies and showtimes
- Users can book seats for a show
- Users can cancel bookings
- System shows available seats (real-time)
- Payments must be processed securely
- Users receive confirmation email
```

**Questions to ask:**
- Can users search by movie, theater, date?
- How long is a seat "locked" during booking?
- What payment methods? (Credit card, UPI, wallet, etc.)
- Can users modify a booking (change time/seats)?

### Non-Functional Requirements

How should it perform?

**Scale:**
- How many concurrent users? (100, 1K, 100K?)
- How many movies/theaters? (100, 1K, 10K?)
- How many bookings per day? (1K, 100K, 1M?)

**Latency:**
- How fast should the page load? (p50, p99)
- How fast should booking confirmation be? (<1s? <100ms?)

**Consistency:**
- Can bookings be oversold? (No! catastrophic)
- Can seat availability be slightly stale? (Probably ok)
- Must bookings survive datacenter failure? (Probably)

**Availability:**
- SLA target? (99%, 99.9%, 99.99%?)
- Graceful degradation during outages? (Show cached movie list, can't book)

### Back-of-Envelope Estimation

**Assumptions to state clearly:**

```
Number of theaters in India: ~10,000
Shows per theater per day: ~6
Movie duration: ~2.5 hours
Seats per theater: ~200

Daily metrics:
Theater × Shows × Seat occupancy
10,000 × 6 × 0.5 (50% occupancy) = 30,000 bookings/day
= 0.35 bookings/second (average)
= ~10 bookings/second (peak, evening shows)

Concurrent users during peak:
Average session duration: 10 minutes
Users/second bookings × concurrent_multiply
10 × 600 = 6,000 concurrent booking operations

But reading activity is 100x booking:
Views/bookings = 1:1000
So 6,000 bookings → 6M page views/day
= ~70 page views/second (average)
= ~2,000 concurrent viewing users
```

**Storage estimation:**

```
Users:
1M registered users × 1KB/user = 1GB

Movies:
100K movies × 50KB/movie = 5GB

Shows/Showtimes:
50K shows (across all theaters) × 10KB/show = 500MB

Bookings (last 2 years):
500M bookings × 1KB/booking = 500GB (searchable)
+ older bookings archived = +500GB

Total: ~1.5TB searchable, ~2TB total
Index overhead: +30% = ~2.5TB

Cache (Redis):
Hot data: today's + tomorrow's shows, today's seat availability
~100K shows × 10KB = 1GB
Users in session: ~10K concurrent × 1KB = 10MB
Total: ~1-2GB
```

**Bandwidth estimation:**

```
Movies played/second: 2,000 users
Avg response size: 100KB
Bandwidth: 2,000 × 100KB = 200MB/second = 1.6Gbps

With CDN:
- Images cached at edge (99% hit rate)
- Only 1% of traffic from origin
- Origin bandwidth: ~16Mbps

Database:
- 70 reads/second average, 2KB each = 140KB/s
- 10 writes/second average = critical path (row locks, transaction overhead)
```

---

## Phase 2: High-Level Design (10 min)

### Draw Boxes and Arrows

**Do this on a whiteboard or collaborative tool. Show:**

```
┌─────────┐
│  Users  │
└────┬────┘
     │
┌────▼──────────────────────────────────┐
│  Load Balancer (HTTPS)                │
└────┬──────────────────────────────────┘
     │
┌────▼──────────────────────────────────┐
│  API Gateway / Auth Service           │
│  ├─ JWT token validation              │
│  └─ Rate limiting                     │
└────┬──────────────────────────────────┘
     │
     ├──────────┬──────────┬──────────┐
     │          │          │          │
  ┌──▼──┐   ┌──▼──┐   ┌──▼──┐   ┌──▼──┐
  │App1 │   │App2 │   │App3 │   │App4 │  (Stateless, horizontal scaling)
  └──┬──┘   └──┬──┘   └──┬──┘   └──┬──┘
     │          │          │          │
     └──────────┼──────────┼──────────┘
                │          │
        ┌───────▼──────────▼────────┐
        │  Database (Primary)       │
        │  Write main DB            │
        ├─ Bookings, Users, Shows   │
        └───────┬──────────┬────────┘
                │          │
           ┌────▼─┐    ┌───▼────┐
           │Read  │    │Read    │  (Replicas for reads)
           │Rep1  │    │Rep2    │
           └──────┘    └────────┘

        ┌──────────────────────────┐
        │  Cache Layer (Redis)     │
        │ - Seat availability      │
        │ - Movie listings         │
        │ - User sessions          │
        └──────────────────────────┘

        ┌──────────────────────────┐
        │  Message Queue (Kafka)   │
        │ - Booking events         │
        │ - Email notifications    │
        └──────────────────────────┘

        ┌──────────────────────────┐
        │  External Services       │
        │ - Payment gateway        │
        │ - Email service          │
        │ - SMS service            │
        └──────────────────────────┘
```

### Core Services (Initial Version)

```
1. Movie Service
   - GET /movies (list with filters)
   - GET /movies/{id} (details)
   - GET /shows (list showtimes)

2. Booking Service
   - POST /bookings (create booking)
   - GET /bookings/{id} (check status)
   - DELETE /bookings/{id} (cancel)
   - GET /seats/{show_id} (availability)

3. Payment Service
   - POST /payments (process payment)
   - GET /payments/{id} (status)
   - Handles idempotency, retries

4. User Service
   - POST /auth/signup
   - POST /auth/login
   - GET /users/profile

5. Notification Service
   - Consumes booking events from Kafka
   - Sends emails, SMS
   - Asynchronous
```

### Data Flow (Normal Happy Path)

```
1. User views movie details
   ├─ Browser requests: GET /movies/123
   ├─ App servers query: db.GetMovie(123) or redis.Get("movie:123")
   ├─ Response: JSON with movie details, all shows

2. User selects show, views seat map
   ├─ Requests: GET /seats/show/456
   ├─ App server checks: redis.GetSeats("show:456")
   ├─ Response: JSON with seat availability

3. User selects seats, initiates booking
   ├─ POST /bookings with {show_id, seat_ids}
   ├─ Booking service:
   │  ├─ Lock seats in Redis (3min TTL)
   │  ├─ Check if still available (confirm no double-booking)
   │  ├─ Create booking record (status="locked")
   │  ├─ Return booking_id to user
   │
   └─ Frontend shows payment form

4. User submits payment
   ├─ POST /payments with {booking_id, card_details}
   ├─ Payment service:
   │  ├─ Validate card with payment gateway
   │  ├─ Charge card
   │  ├─ Update booking status="confirmed"
   │  ├─ Publish event "BookingConfirmed" to Kafka
   │
   └─ Return success to user

5. Background: Notification service consumes event
   ├─ Receives "BookingConfirmed" message
   ├─ Sends confirmation email
   ├─ Publishes "EmailSent" event
```

---

## Phase 3: Deep Dive (20 min)

Pick 2-3 hardest problems and go deep. For movie booking, these are:

### Deep Dive 1: Seat Locking and Race Conditions

**The problem:**
```
Show has 1 seat left.
User A and User B both try to book simultaneously.

Timeline:
T0: A checks availability → 1 seat left
T0: B checks availability → 1 seat left
T1: A locks seat (success)
T2: B tries to lock same seat → CONFLICT!
```

**Solution: Pessimistic Locking (exclusive lock)**

```go
func BookSeats(ctx context.Context, showID, userID string, seatIDs []string) (*Booking, error) {
    // Acquire exclusive lock on seats
    for _, seatID := range seatIDs {
        key := fmt.Sprintf("lock:seat:%s:%s", showID, seatID)

        // Try to acquire lock with 3-minute TTL
        ok := redis.SetNX(ctx, key, userID, 3*time.Minute)
        if !ok {
            return nil, fmt.Errorf("seat already locked by %v", redis.Get(ctx, key))
        }
    }

    // Seats locked! Now we can safely proceed
    booking := &Booking{
        ID:        generateID(),
        ShowID:    showID,
        UserID:    userID,
        Seats:     seatIDs,
        Status:    "locked",
        ExpiresAt: time.Now().Add(5 * time.Minute),  // Lock expires in 5 min
    }

    // Save booking to DB
    if err := db.SaveBooking(ctx, booking); err != nil {
        // Rollback locks!
        for _, seatID := range seatIDs {
            key := fmt.Sprintf("lock:seat:%s:%s", showID, seatID)
            redis.Delete(ctx, key)
        }
        return nil, err
    }

    return booking, nil
}

// When user completes payment
func ConfirmBooking(ctx context.Context, bookingID string) error {
    booking := db.GetBooking(ctx, bookingID)

    // Unlock seats (permanent now that booking confirmed)
    for _, seatID := range booking.Seats {
        key := fmt.Sprintf("lock:seat:%s:%s", booking.ShowID, seatID)
        redis.Delete(ctx, key)
    }

    // Mark as confirmed in DB
    booking.Status = "confirmed"
    return db.SaveBooking(ctx, booking)
}

// Fallback: timer expires locks
// If user closes browser without confirming: lock held for 3 minutes
// Then automatically released (seat becomes available again)
```

**Alternative: Optimistic Locking (version numbers)**

```go
type Seat struct {
    ID       string
    ShowID   string
    Status   string  // "available" or "booked"
    Version  int     // Incremented on each change
}

func BookSeat(ctx context.Context, seatID string, expectedVersion int) error {
    // Read current state
    seat := db.GetSeat(ctx, seatID)

    // Check if version still matches
    if seat.Version != expectedVersion {
        return fmt.Errorf("seat was modified, try again")
    }

    // Try to update with version check
    updated := db.UpdateSeat(ctx, &Seat{
        ID:      seatID,
        Status:  "booked",
        Version: expectedVersion + 1,
    }, whereVersion: expectedVersion)

    if !updated {
        return fmt.Errorf("concurrent update, try again")
    }
    return nil
}
```

**Comparison:**

| Aspect | Pessimistic (Lock) | Optimistic (Version) |
|--------|-------------------|----------------------|
| Contention | High | High |
| Lock timeout | Automatic | Immediate (client retries) |
| Complexity | Simple | Requires retry logic |
| Performance | Slow (lots of lock holders) | Faster (less waiting) |
| Movie booking | GOOD! | Not suitable |

For movie booking: use pessimistic locking (seats are scarce during shows, expect high contention, need locks).

### Deep Dive 2: Database Schema and Indexing

**Core Tables:**

```sql
-- Users
CREATE TABLE users (
    id UUID PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(20),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Movies
CREATE TABLE movies (
    id UUID PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    genre VARCHAR(50),
    duration_minutes INT,
    release_date DATE,
    poster_url VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_movies_release_date ON movies(release_date DESC);
CREATE INDEX idx_movies_genre ON movies(genre);

-- Theaters
CREATE TABLE theaters (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    city VARCHAR(100) NOT NULL,
    address TEXT,
    seats_total INT,
    latitude DECIMAL(9, 6),
    longitude DECIMAL(9, 6),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_theaters_city ON theaters(city);
CREATE INDEX idx_theaters_location ON theaters USING gist(ll_to_earth(latitude, longitude));

-- Shows (Showtimes)
CREATE TABLE shows (
    id UUID PRIMARY KEY,
    movie_id UUID NOT NULL REFERENCES movies(id),
    theater_id UUID NOT NULL REFERENCES theaters(id),
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    seats_available INT NOT NULL,
    seats_total INT NOT NULL,
    price_per_seat DECIMAL(10, 2),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_shows_movie_id ON shows(movie_id);
CREATE INDEX idx_shows_theater_id ON shows(theater_id);
CREATE INDEX idx_shows_start_time ON shows(start_time);
-- Composite index for common query
CREATE INDEX idx_shows_movie_theater_date
  ON shows(movie_id, theater_id, DATE(start_time));

-- Seats (per show)
CREATE TABLE seats (
    id UUID PRIMARY KEY,
    show_id UUID NOT NULL REFERENCES shows(id),
    seat_number VARCHAR(10) NOT NULL,  -- "A1", "A2", etc.
    status VARCHAR(20) DEFAULT 'available',  -- available, booked, locked
    locked_until TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_seats_show_seat ON seats(show_id, seat_number);
CREATE INDEX idx_seats_show_status ON seats(show_id, status);  -- For availability queries

-- Bookings
CREATE TABLE bookings (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    show_id UUID NOT NULL REFERENCES shows(id),
    booking_time TIMESTAMP DEFAULT NOW(),
    status VARCHAR(20) DEFAULT 'locked',  -- locked, confirmed, cancelled
    total_amount DECIMAL(10, 2),
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_bookings_user_id ON bookings(user_id, created_at DESC);
CREATE INDEX idx_bookings_show_id ON bookings(show_id);
CREATE INDEX idx_bookings_status ON bookings(status);
-- For finding booking by user + show (prevent double-booking)
CREATE UNIQUE INDEX idx_bookings_user_show_active
  ON bookings(user_id, show_id)
  WHERE status IN ('locked', 'confirmed');

-- Booking Items (seats in a booking)
CREATE TABLE booking_items (
    id UUID PRIMARY KEY,
    booking_id UUID NOT NULL REFERENCES bookings(id),
    seat_id UUID NOT NULL REFERENCES seats(id),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_booking_items_booking_id ON booking_items(booking_id);
CREATE UNIQUE INDEX idx_booking_items_seat_booking
  ON booking_items(seat_id, booking_id);  -- Prevent double-adding

-- Payments
CREATE TABLE payments (
    id UUID PRIMARY KEY,
    booking_id UUID NOT NULL REFERENCES bookings(id),
    user_id UUID NOT NULL REFERENCES users(id),
    amount DECIMAL(10, 2),
    status VARCHAR(20) DEFAULT 'pending',  -- pending, success, failed, refunded
    payment_method VARCHAR(50),
    transaction_id VARCHAR(255) UNIQUE,  -- From payment gateway (idempotency)
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_payments_booking_id ON payments(booking_id);
CREATE INDEX idx_payments_user_id ON payments(user_id);
CREATE INDEX idx_payments_transaction_id ON payments(transaction_id);
```

**Query Patterns and Index Strategy:**

```sql
-- #1 Search movies by genre, release date (common)
SELECT * FROM movies
WHERE genre = 'Action' AND release_date > NOW() - INTERVAL '30 days'
ORDER BY release_date DESC
LIMIT 10;
-- Use: idx_movies_genre, idx_movies_release_date (covering index better)

-- #2 Get all shows for a movie
SELECT shows.*, theaters.name, movies.title
FROM shows
JOIN theaters ON shows.theater_id = theaters.id
JOIN movies ON shows.movie_id = movies.id
WHERE shows.movie_id = ? AND shows.start_time > NOW()
ORDER BY shows.start_time;
-- Use: idx_shows_movie_id

-- #3 Get available seats for a show (CRITICAL QUERY)
SELECT * FROM seats
WHERE show_id = ? AND status = 'available'
ORDER BY seat_number;
-- Use: idx_seats_show_status (cover status=available efficiently)

-- #4 Check if user already booked this show (prevent double-booking)
SELECT COUNT(*) FROM bookings
WHERE user_id = ? AND show_id = ? AND status IN ('locked', 'confirmed');
-- Use: idx_bookings_user_show_active (partial index!)

-- #5 Get user's bookings history
SELECT bookings.*, shows.start_time, movies.title
FROM bookings
JOIN shows ON bookings.show_id = shows.id
JOIN movies ON shows.movie_id = movies.id
WHERE bookings.user_id = ?
ORDER BY bookings.created_at DESC
LIMIT 20;
-- Use: idx_bookings_user_id (with user_id, created_at DESC)

-- #6 Find expired locks (for cleanup)
SELECT * FROM bookings
WHERE status = 'locked' AND expires_at < NOW();
-- Use: idx_bookings_status (partial: WHERE status='locked')
```

**Denormalization for Performance:**

```sql
-- Instead of always joining:
SELECT shows.seats_available FROM shows WHERE id = ?
-- Cache this in Redis! Seats_available changes frequently

-- Denormalize in bookings table:
ALTER TABLE bookings ADD COLUMN movie_title VARCHAR(255);
-- When creating booking, store movie title (avoid JOIN)

-- Use materialized view for reporting:
CREATE MATERIALIZED VIEW bookings_by_genre AS
SELECT
    movies.genre,
    DATE(shows.start_time) as booking_date,
    COUNT(*) as booking_count,
    SUM(payments.amount) as revenue
FROM bookings
JOIN shows ON bookings.show_id = shows.id
JOIN movies ON shows.movie_id = movies.id
JOIN payments ON bookings.id = payments.booking_id
WHERE bookings.status = 'confirmed'
GROUP BY movies.genre, DATE(shows.start_time);

-- Refresh every hour
REFRESH MATERIALIZED VIEW bookings_by_genre;
```

### Deep Dive 3: Handling Concurrent Bookings at Scale

**Scenario: Major movie release, 1000 concurrent bookings for same show**

```
Show: Avatar 3, Theater: Delhi Inox, Seats: 300
Time: 5pm, Release day

All 1000 users book simultaneously
Only 300 seats
Who gets them?

Current approach breaks:
- All 1000 try to lock seats
- All 1000 execute SELECT available seats
- Race conditions: users see 1 seat left, 1000 try to book it
```

**Solution: Change strategy for high-contention shows**

```go
func BookSeatHighContention(ctx context.Context, showID string, userID string) (*Booking, error) {
    // Instead of selecting specific seats, assign seats algorithmically

    // 1. Increment atomic counter (Redis INCR)
    bookingNumber, err := redis.Incr(ctx, fmt.Sprintf("bookings:counter:%s", showID))
    if err != nil {
        return nil, fmt.Errorf("show fully booked")
    }

    // 2. Check if we exceeded capacity
    show := db.GetShow(ctx, showID)
    if bookingNumber > show.SeatsTotal {
        // Too late! Show is full
        redis.Decr(ctx, fmt.Sprintf("bookings:counter:%s", showID))  // Undo increment
        return nil, fmt.Errorf("show fully booked")
    }

    // 3. Assign seat based on booking number (deterministic)
    seatNumber := bookingNumber - 1  // 0-indexed
    seatName := IntToSeatNumber(seatNumber)  // 0 → "A1", 1 → "A2", etc.

    // 4. Create booking with assigned seat (no locking race conditions!)
    booking := &Booking{
        ID:          generateID(),
        ShowID:      showID,
        UserID:      userID,
        SeatNumber:  seatName,
        Status:      "locked",
        ExpiresAt:   time.Now().Add(5 * time.Minute),
    }

    return db.SaveBooking(ctx, booking), nil
}

func IntToSeatNumber(seatNum int) string {
    // 0 → "A1", 99 → "E0", 100 → "F1", etc.
    row := rune('A' + (seatNum / 10))
    col := seatNum % 10
    return fmt.Sprintf("%c%d", row, col)
}
```

**Advantage:** No locking, no race conditions, atomic counter handles fairness.

**Downside:** Users don't choose seats for high-demand shows (they get assigned).

**Trade-off:** For Avatar 3 release day, users would rather get any seat than go home empty-handed. Let them choose seats on slow days.

---

## Phase 4: Wrap-up (10 min)

### Identify Bottlenecks

```
1. Database writes: All seat changes go through single database
   Solution: Shard by show_id, or use local locks before writing

2. Seat availability queries: 1000 concurrent users checking same show
   Solution: Cache in Redis with TTL, accept slight staleness

3. Seat selection locking: Users hold locks for 5 minutes
   Solution: Shorter TTL (2 min), or assign seats instead of choosing

4. Payment processing: Synchronous payment gateway calls
   Solution: Queue payments, retry async, show pending state

5. Email notifications: Sending 1M emails after booking surge
   Solution: Queue in Kafka, process with worker threads
```

### Monitoring and Alerting

```
Metrics to track:
- Booking success rate (% that complete vs. fail)
- Average seat lock duration
- Cache hit rate (should be >95%)
- Database write latency (p50, p99)
- Payment processing latency
- Queue depth (Kafka, email queue)

Alerts:
- Booking success rate < 95% → investigate
- Cache hit rate < 90% → likely cache issue
- Payment latency > 5s → external gateway slow
- Queue depth > 10K → workers can't keep up
- Database CPU > 80% → capacity planning
```

### Failure Modes

```
Failure 1: Payment gateway is down
├─ Bookings locked, but can't confirm
├─ Seats tied up for 5 minutes
├─ Mitigate: fail fast, unlock seats immediately, retry user later

Failure 2: Email service is down
├─ Bookings confirmed, but user doesn't know
├─ Mitigate: async email, retry logic, confirmation code in SMS/app

Failure 3: Database replication lag
├─ User pays, checks booking status
├─ Replica doesn't have confirmation yet
├─ Mitigate: route reads to primary after recent writes, use session affinity

Failure 4: Redis goes down
├─ Can't check seat locks
├─ Options:
│  a) Use database for locks (slower)
│  b) Fail-open: assume seat is available (might oversell)
│  c) Fail-closed: reject bookings until Redis recovers
└─ Recommend: fail-closed (better to reject than oversell)

Failure 5: Entire datacenter offline
├─ All bookings stop
├─ Mitigate: geo-distributed replicas, failover to backup datacenter
```

---

## Back-of-Envelope Estimation

### Numbers Every Backend Engineer Should Know

```
Latencies (2024, approximate):
├─ L1 cache reference: 1 ns
├─ Main memory reference: 100 ns
├─ SSD read: 16 us (16,000 ns)
├─ HDD seek + read: 10 ms (10,000,000 ns)
├─ Network roundtrip (same datacenter): 1 ms
├─ Network roundtrip (cross-country): 100 ms
├─ Network roundtrip (around world): 200-300 ms
├─ Database query (simple): 1-10 ms
├─ Database query (complex join): 50-500 ms
├─ Payment gateway call: 500-2000 ms
└─ User perceivable lag: >100ms

Storage (modern drives):
├─ SSD: 1-2 TB, $100-200
├─ HDD: 4-8 TB, $150-250
├─ RAM: 64GB, $200-400

Bandwidth:
├─ 1 Gigabit ethernet: 125 MB/sec
├─ 10 Gigabit ethernet: 1.25 GB/sec
├─ CDN egress: $0.085/GB (AWS)

Compute (cloud):
├─ 4-core server: $0.1-0.3/hour
├─ 8-core server: $0.3-0.6/hour
├─ 16-core server: $0.8-1.5/hour
```

### Estimation Technique

**For every system design, estimate:**

1. **DAU (Daily Active Users)**
   ```
   Movie booking: 100M people in India × 1% who book monthly
   = 1M monthly = ~33K daily = DAU 33K
   ```

2. **QPS (Queries Per Second)**
   ```
   33K users × 10 actions/user/day ÷ (86,400 seconds)
   = ~3.8 QPS average
   Peak (evening): 20x average = ~75 QPS
   ```

3. **Peak Concurrent Users**
   ```
   QPS × average session duration
   75 QPS × 5 minutes = 75 × 300 = 22,500 concurrent users
   ```

4. **Storage**
   ```
   1M users × 1KB = 1GB
   100K movies × 50KB = 5GB
   500M bookings (5 years) × 1KB = 500GB
   Total: ~600GB
   With indices: ~1TB
   ```

5. **Bandwidth**
   ```
   Read-heavy: 100 reads per booking
   75 QPS peak × 100 reads = 7,500 read QPS
   Avg response: 100KB = 750 MB/sec = 6 Gbps (during peak)
   ```

6. **Cost**
   ```
   Servers: 10 servers × $300/month = $3K
   Database: managed RDS × $1K = $1K
   Cache: Redis × $500 = $500
   CDN: 6Gbps × $0.085/GB × 86,400 sec = $44K/month (!!)
   Total: ~$50K/month

   Per user: $50K ÷ 33K = $1.50/user/month
   Acceptable if avg booking is $20+
   ```

---

## Full Worked Example: Movie Booking System

### Requirements (5 min)

**Functional:**
- Users view movies/showtimes
- Users book seats
- Users cancel bookings
- Payment processing
- Confirmation emails

**Non-Functional:**
- 100K concurrent users during peak
- <1s booking confirmation
- 99.9% availability (allow 8.6 hours downtime/year)
- No overselling (consistency critical)
- Regional deployment (India, then expand)

### Estimation (5 min)

```
Population: 1.4B in India
Daily moviegoers: 1% = 14M
Bookings through app: 50% = 7M/day
Average bookings/user: 10/month = 7M ÷ 30 / 0.1 = 233K users/day

QPS: 7M bookings/day ÷ 86,400 sec = 81 bookings/second
+ reads (100x): 8,100 read QPS
Peak (8pm show release): 10x = 81,000 read QPS

Storage (2 years):
Bookings: 7M × 365 × 2 × 1KB = 2.5TB
Movies: 1K × 50KB = 50MB
Users: 3M × 1KB = 3GB
Shows: 50K × 10KB = 500MB
Total: ~2.5TB

Concurrent: 81,000 QPS peak × 5min avg session = 24M concurrent (!)
Actually: peak is 1-2 hours only, reserve 10K servers
Cost: 10K servers × $300 = $3M/month (!!)
```

**Adjust assumptions:**
```
Actual concurrent: 100K (given in requirements)
This means: 100K users × 5min = 500K QPS for reading
= ~500 booking operations/second during peak
More realistic, aligns with single-theater bookings

Per-user data footprint: 10KB for session state
100K users × 10KB = 1GB (cache layer)

Database: 500 bookings/sec = manageable on 3-node cluster
```

### High-Level Architecture (10 min)

```
[Users]
   │
   └─→ [CDN] (static assets)

[Load Balancer] (geographical routing)
   ├─→ [India DC]
   │   ├─→ [API Servers] (10 servers)
   │   ├─→ [PostgreSQL Primary]
   │   ├─→ [PostgreSQL Replica] (2x)
   │   ├─→ [Redis Cluster] (3 nodes)
   │   └─→ [Kafka] (3 brokers)
   │
   └─→ [Backup DC] (failover)
       ├─→ [PostgreSQL Replica]
       └─→ [Redis Replica]

[Background Services] (workers)
├─→ [Email Notifications] (Kafka → Email)
├─→ [Analytics] (Kafka → BigQuery)
├─→ [Lock Cleanup] (expires old locks)
└─→ [Payment Retry] (async payment processing)
```

### Deep Dives (20 min)

**Deep Dive 1: Seat Locking**
- Pessimistic locking in Redis with 3-minute TTL
- Atomic operations to prevent double-booking
- Lock expiration for abandoned bookings

**Deep Dive 2: Payment Idempotency**
- Idempotency keys (user's device generates UUID)
- Payment status table stores transaction_id
- Retry-safe: same key always returns same result

**Deep Dive 3: Database Sharding**
- Shard by movie_id (seat availability is per-movie, parallelizable)
- Shard key: hash(movie_id) % 10 = shard ID
- Each shard has primary + 2 replicas

### Bottleneck Analysis (10 min)

```
Bottleneck 1: Seat availability queries
├─ 500 queries/second for same show
├─ Solution: Cache in Redis, 5-second TTL
├─ Fallback: Database query (acceptable slight staleness)

Bottleneck 2: Seat locking
├─ 500 lock acquisitions/second during peak
├─ Solution: Use Redis (very fast, <1ms)
├─ Fallback: Database pessimistic locking (slower)

Bottleneck 3: Payment processing
├─ 100 payments/second (10% of bookings are fast bookers)
├─ Solution: Async queue, process in parallel
├─ SLA: within 5 minutes of booking

Bottleneck 4: Database writes
├─ 500 writes/second, 10+ writes per booking
├─ Solution: Batch writes, async analytics
├─ Expected p99 latency: <100ms

Bottleneck 5: Email notifications
├─ 500 emails/second after booking
├─ Solution: Kafka queue + worker threads
├─ SLA: within 5 minutes
```

---

## Full Worked Example: WhatsApp Messaging System

### Requirements

**Functional:**
- Send text messages (1-on-1)
- Group messages
- Message delivery guarantees (at-least-once)
- Read receipts
- Online/offline presence
- Push notifications

**Non-Functional:**
- 2B monthly active users
- 100B messages/day
- Message latency: <100ms (p99)
- 99.99% availability (high availability)
- End-to-end encryption (mention but don't deep dive)

### Estimation

```
Users: 2B MAU, ~500M DAU
Messages: 100B/day
Messages/second: 100B ÷ 86,400 = 1.16M msg/sec (average)
Peak (evening): 10x = 11.6M msg/sec

Storage (keep 30 days hot):
100B messages/day × 30 days × 500B (compressed) = 15EB (exabytes!)
Not feasible in hot storage. Need:
├─ Hot (30 days): 1.5PB (SSD)
├─ Warm (90 days): 4.5PB (HDD)
└─ Cold (archive): S3/GCS

Bandwidth:
11.6M msg/sec × 1KB message = 11.6TB/sec peak
= 92.8 Pbps (petabits/second) (!!)
Actual: with compression + local batch = ~1Pbps

Servers:
11.6M msg/sec ÷ 10K msg/sec per server = 1,160 servers
Plus replicas, cache, etc: ~5,000 servers

Cost: 5,000 × $300 = $1.5M/month + external costs
```

### High-Level Architecture

```
[WhatsApp Clients]
  │
  ├─→ [WebSocket/QUIC Connection] (low-latency, persistent)
  │
[Load Balancer] (connection routing)
  │
[Gateway Servers] (10,000+ servers globally distributed)
  ├─ Handle WebSocket connections
  ├─ Maintain connection state
  └─ Route messages to recipients
  │
[Message Queue] (Kafka, 100+ clusters)
  ├─ Each region has own cluster
  ├─ Partition by user_id: hash(user_id) % 10K partitions
  └─ Replicated across 3 datacenters (2 within region, 1 backup)
  │
[Message Storage] (Cassandra or similar)
  ├─ Hot (30 days): SSD, every region
  ├─ Warm (90 days): HDD, one region
  └─ Cold (archive): S3/GCS
  │
[Presence Service] (Redis cluster)
  ├─ User online/offline status
  ├─ Last seen timestamp
  └─ Device presence (mobile, web, desktop)
  │
[Delivery Confirmation] (local databases)
  ├─ Message receipt status (sent, delivered, read)
  ├─ Retry logic (resend if not acknowledged)
  └─ Per-region for low latency
  │
[Background Services]
  ├─ Push notification (delivered ÷ online status = need to push)
  ├─ Read receipt propagation (send back to sender)
  └─ Group message fan-out (1 message → 50 members)
```

### Message Flow (1-on-1)

```
User A sends to User B:

1. A's client:
   ├─ Generate message ID (locally unique)
   ├─ Encrypt message (E2E)
   └─ Send via WebSocket to gateway

2. Gateway A:
   ├─ Receive message
   ├─ Validate (user auth, rate limit)
   ├─ Add server timestamp
   ├─ Publish to Kafka: partition(B's user_id)

3. Kafka:
   ├─ Replicate across 3 brokers
   ├─ Return to gateway: "offset=12345"
   └─ Gateway returns to A: "message_id accepted"
   ├─ A's client shows: "sent" (check mark)

4. Message Storage:
   ├─ Consumer reads from Kafka
   ├─ Writes to Cassandra
   ├─ Indexed by (recipient_id, timestamp)

5. B's Gateway:
   ├─ If B online:
   │  ├─ Send message to B's WebSocket
   │  └─ B's client shows: "delivered" (check mark)
   │
   └─ If B offline:
      ├─ Store in queue for B
      └─ Schedule push notification

6. B's Client:
   ├─ Receive message
   ├─ Show in conversation
   ├─ User reads message
   ├─ Send read receipt back to A's gateway
   └─ A shows: "read" (two blue check marks)
```

### Deep Dive: Presence and Online Status

```
Challenge: 2B users, need to know who's online NOW
Can't check database for every message (too slow)

Solution: Redis Pub/Sub + in-memory state

User A comes online:
├─ Client: POST /api/presence/online
├─ Gateway: Publish to Redis "user:A:online"
├─ All subscribed gateways: hear event
├─ Update local cache: A is online
├─ If B has A's chat open: show A as online

When A sends message to B:
├─ Gateway checks local cache: is B online?
├─ If yes: direct send via WebSocket
├─ If no: queue + push notification

Presence is eventually consistent:
├─ If connection drops: 30-60 second delay before "offline"
├─ Users see "last seen X minutes ago"
├─ Better UX than ping-ponging constantly
```

### Deep Dive: Group Messages

```
Challenge: 1 message → 1M members (groups)
Can't send 1M separate messages (too slow)

Solution: Fan-out

User A posts to group with 1M members:

1. A sends message
2. Message stored in database
3. Publish event: "group:123:new_message"
4. Subscribe to this event:
   ├─ [Group notification workers] (100 workers)
   ├─ [Read receipt handlers]
   └─ [Archive workers]

5. Group notification workers:
   ├─ Batch operations: process 1000s at a time
   ├─ For each member: decide - send or queue
   ├─ If online: direct send
   ├─ If offline: add to member's queue

6. Push notification workers:
   ├─ Check which members are offline
   ├─ Send push notifications
   ├─ Respect quiet hours (don't push at night)

Timings:
├─ Immediate (members online): <100ms
├─ Eventually (offline members): <5 minutes (when they come online)
```

---

## Common Questions with Approach

### 1. Design a URL Shortener (like bit.ly)

**Approach:**
```
Estimate: 1M shortened URLs/day
Storage: 1M × 365 × 10 = 3.65B total URLs
Short code: 6 chars, 62^6 = 56T possible

Sharding:
├─ Shard by first char of short code (a-z, 0-9) = 62 buckets
└─ Each shard: 3.65B ÷ 62 = ~60M URLs

Database:
├─ short_code (PK), long_url, created_at, click_count
├─ Index on short_code (unique)
├─ Cache hot URLs (daily)

API:
├─ POST /shorten?url=https://example.com
   └─ Generate short code, save, return shortlink
├─ GET /{short_code}
   └─ Lookup, increment counter, redirect to long_url

Challenges:
├─ Collision: same URL shortened twice
   └─ Solution: check for existing before generating new
├─ Collision: two services generate same short code
   └─ Solution: unique constraint in database (fail, retry)
├─ Hot URLs: https://bit.ly/xxx redirected 1M times/day
   └─ Solution: cache in Redis, invalidate periodically
```

### 2. Design a Rate Limiter

**Approach:**
```
Estimate: 1M API requests/second
Rate limit: 100 requests per minute per user

Algorithm: Token Bucket
├─ User bucket: 100 tokens max
├─ Refill: 1 token per 0.6 seconds (100 tokens in 60 seconds)
├─ Request: costs 1 token
├─ If bucket empty: reject (429 Too Many Requests)

Implementation:
├─ Redis: HASH per user {user_id: {tokens: 95, last_refill: timestamp}}
├─ On request:
│  ├─ Calculate tokens to add: (now - last_refill) / 0.6
│  ├─ tokens += refilled_tokens
│  ├─ tokens = min(tokens, 100)
│  ├─ If tokens > 0: grant, tokens--, return 429 else
│  └─ Update last_refill = now

Distributed rate limiting:
├─ Single Redis: single point of failure
├─ Redis cluster: consistent hashing by user_id
├─ Accept slight inaccuracy (user might exceed limit briefly)
```

### 3. Design a Notification System

**Approach:**
```
Events trigger notifications:
├─ User posts → notify followers
├─ User follows → notify user
├─ System event → notify relevant users

Architecture:
├─ Event source (posting, following) publishes to Kafka
├─ Notification service consumes events
├─ Decides: who to notify, which channel (email/SMS/push)
├─ Stores notification status
├─ Workers send notifications asynchronously

Database:
├─ notifications: (id, user_id, event_type, content, status, created_at)
├─ notification_prefs: (user_id, channel, enabled_at, category)

Channels:
├─ In-app: instant (WebSocket)
├─ Email: within 5 minutes
├─ SMS: within 30 seconds (critical only)
├─ Push: within 2 minutes

Challenges:
├─ Spam: user follows celebrity → 1M notifications
   └─ Solution: batch them, deduplicate
├─ Delivery: email addresses invalid
   └─ Solution: mark as bounced, stop sending
├─ Preferences: user turns off notifications
   └─ Solution: query preference table before sending
```

### 4. Design a News Feed (like Twitter)

**Approach:**
```
Challenge: Show personalized feed for 500M users
Must include: posts from follows, trending, timeline

Approach 1: Timeline Fanout (precompute)
├─ When user A posts:
│  ├─ Find all followers (A has 1K followers)
│  ├─ Push post to each follower's feed queue
│  └─ Takes 1 second, but feed is ready instantly

Approach 2: Lazy Load (on-demand)
├─ User opens feed
├─ Query: posts from followed users (last 24h)
├─ Join with likes, retweets, comments
├─ Slow (might be 1-2 second)

Hybrid:
├─ Fanout for regular users (<10K followers)
├─ Lazy load for celebrities (>10K followers, expensive to fanout)

Database:
├─ posts: (id, user_id, content, created_at, likes, retweets)
├─ feeds: (user_id, post_id, timestamp)
  └─ Sharded by user_id (hot storage: last 7 days)
├─ comments: (id, post_id, user_id, content)

Timeline cache:
├─ Redis list per user: user_id:timeline = [post_5, post_4, post_3, ...]
├─ TTL: 30 minutes (expires to reduce memory)
├─ On feed load: fetch from cache + new posts since cache time
```

---

## Red Flags and How to Avoid Them

### Red Flag 1: Lack of Estimation

**Bad:**
"The system will handle millions of users"
(vague, no concrete math)

**Good:**
"Estimated 100K concurrent users at peak.
500 bookings/sec = 10M per day.
Storage: 1TB for 2 years."

### Red Flag 2: Over-Engineering

**Bad:**
"We'll use Kubernetes, Kafka, Elasticsearch, and microservices
for a 100 QPS system."
(massive overkill)

**Good:**
"Start with single PostgreSQL + Redis on one server.
When we hit 10K QPS, shard the database.
Add Kafka for notifications when asynchrony is needed."

### Red Flag 3: Ignoring Failures

**Bad:**
(draws perfect architecture with no failure discussion)

**Good:**
"Database failover: replicas take over in <1 minute.
Network partition: use circuit breakers to fail fast.
Payment service down: queue payments, retry async."

### Red Flag 4: Missing Consistency Discussion

**Bad:**
(treats all data as same consistency level)

**Good:**
"Bookings are strongly consistent (pessimistic locking).
Seat availability cached (eventually consistent, 5s TTL).
User profiles eventually consistent (async replication)."

### Red Flag 5: No Monitoring Plan

**Bad:**
(architecture drawn, interviewer asks "how do you know if it works?")

**Good:**
"Metrics: booking success rate, p99 latency, cache hit rate.
Alerts: booking rate drops, latency >500ms, cache hit <90%.
Dashboards for on-call engineers."

### Red Flag 6: Not Asking Questions

**Bad:**
(assumes requirements, builds system based on misunderstanding)

**Good:**
"Can users change seats after booking?
What's the SLA? 99% or 99.9%?
Do we support international payments?"

---

## Interview Meta-Questions

### 1. "What would you do differently at 1M users?"

**Good answer:**
"At 100K, we have single database primary + replicas.
At 1M, primary becomes bottleneck (writes hit limit).
I'd shard by show_id or user_id.
Each shard has own primary + replicas.
Add consistent hashing for even distribution."

### 2. "How would you handle a major outage?"

**Good answer:**
"Immediate:
- Declare incident, page on-call team
- Fail over to backup datacenter
- Communicate to users (API returns maintenance message)

Investigation:
- Check logs, metrics for root cause
- If database down: check replication, run repair
- If network down: check DNS, BGP routing

Recovery:
- Bring down primary carefully (drain connections)
- Verify backup is healthy
- Switch traffic gradually (canary rollout)

Post-mortem:
- What failed? Why wasn't it caught?
- Add monitoring, alerting, testing for this failure
- Update runbooks"

### 3. "How do you handle a thundering herd?"

**Good answer:**
"Thundering herd: all servers restart, all try to fill cache,
database gets crushed, cascades.

Prevention:
- Cache with probabilistic expiration (refresh at 90% TTL)
- Distributed locking (only one fills cache)
- Fallback to stale data (return old value on DB error)

On restart:
- Stagger restarts (10% per minute)
- Start with circuit breaker open (don't query DB initially)
- Gradually open circuit breaker
- Monitor queue depth"

### 4. "Design the payment flow with idempotency"

**Good answer:**
"Payment must be idempotent (retry-safe).

Flow:
1. Client generates idempotency_key = UUID (locally generated)
2. POST /payments { booking_id, amount, idempotency_key }
3. Server checks: is idempotency_key in cache?
   - Yes: return previous result (might be pending or completed)
   - No: proceed to step 4
4. Call payment gateway with idempotency_key
5. Gateway also checks: seen this key before?
   - Yes: return previous charge_id
   - No: charge card, return charge_id
6. Store result: cache.SET(idempotency_key, {status, charge_id}, 1 day)
7. Return to client: {status: 'pending', charge_id}

On retry:
- Client resends with same idempotency_key
- Cache hit: return immediately (same previous result)
- If payment gateway was slow but succeeded: client sees 'pending'
  initially, sees 'completed' on refresh"

### 5. "Walk me through a database query optimization"

**Good answer:**
"Slow query: 'Get all bookings for user in last month'

```sql
SELECT bookings.*, shows.start_time, movies.title
FROM bookings
JOIN shows ON bookings.show_id = shows.id
JOIN movies ON shows.movie_id = movies.id
WHERE bookings.user_id = ? AND bookings.created_at > NOW() - INTERVAL '30 days'
ORDER BY bookings.created_at DESC
```

Analysis:
1. EXPLAIN shows: full table scan on bookings (bad)
2. Add index: idx_bookings_user_date
   `CREATE INDEX idx_bookings_user_date ON bookings(user_id, created_at DESC)`
3. Add covering index to avoid JOINs:
   `CREATE INDEX idx_bookings_cover ON bookings(user_id, created_at)
    INCLUDE (show_id, status)`
4. Denormalize: add show.start_time to bookings table
5. Cache: user's bookings cached in Redis (TTL 1 hour)

Result:
- Without cache/index: 500ms
- With index: 10ms
- With covering index: 5ms
- With cache: <1ms (95% hits)"

