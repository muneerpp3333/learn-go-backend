# CQRS: Command Query Responsibility Segregation

## The Problem

Your BookingService needs to support two very different access patterns:

1. **Write**: User books a seat (slow, expensive, must be transactional, single user)
   ```
   INSERT INTO bookings (user_id, showtime_id, seat_id, status) VALUES (...)
   UPDATE seats SET reserved = true WHERE id = 'seat-123'
   10ms latency, 1000 RPS capacity
   ```

2. **Read**: Booking dashboard queries (fast, cheap, no transactions, multi-user)
   ```
   SELECT COUNT(*) as total_bookings, SUM(revenue) as total_revenue
   FROM bookings
   WHERE created_at > NOW() - INTERVAL 24 HOURS
   1ms latency, 100,000 RPS capacity
   ```

**The problem**: The same database schema serves both. Optimizing for writes (normalized, ACID transactions) makes reads slow. Optimizing for reads (denormalized, aggregates pre-computed) makes writes slow.

**Example**: You normalize bookings:
```sql
CREATE TABLE bookings (id UUID, user_id UUID, showtime_id UUID, status VARCHAR);
CREATE TABLE bookings_detail (booking_id UUID, seat_row INT, seat_col INT, price DECIMAL);
```

Every booking read requires a JOIN. But writes are fast.

Or you denormalize:
```sql
CREATE TABLE bookings (id UUID, user_id UUID, showtime_id UUID, status VARCHAR,
                       seat_row INT, seat_col INT, price DECIMAL, ...);
```

Reads are fast, but writes duplicate data.

**CQRS separates reads and writes:**
- **Write model**: Normalized, optimized for correctness and consistency
- **Read model**: Denormalized, optimized for queries and reporting

## Theory: CQRS Variations

### Simple CQRS: Same Database, Different Models

**Write path:**
```go
// BookingService: Normalized schema, transactions
func CreateBooking(ctx context.Context, req *CreateBookingRequest) error {
    tx := db.Begin(ctx)
    tx.Exec("INSERT INTO bookings ...")
    tx.Exec("UPDATE seats SET reserved = true ...")
    tx.Commit()
}
```

**Read path:**
```go
// Dashboard: Different queries, no joins
func GetDashboardStats(ctx context.Context) *DashboardStats {
    // Query a pre-computed view or materialized table
    return db.QueryRow(`
        SELECT total_bookings, total_revenue, avg_booking_value
        FROM booking_stats
        WHERE date = CURRENT_DATE
    `)
}
```

**Update the read model when writes happen:**
```go
func CreateBooking(ctx context.Context, req *CreateBookingRequest) error {
    // ... write to normalized schema ...

    // Update read model
    db.Exec(`
        UPDATE booking_stats
        SET total_bookings = total_bookings + 1,
            total_revenue = total_revenue + $1
        WHERE date = CURRENT_DATE
    `, price)
}
```

**Pros:**
- Single database
- Simpler than full CQRS
- Works for most applications

**Cons:**
- Write and read updates must be coordinated (same transaction or eventual consistency)
- If read update fails, write succeeded but read model is stale

### Full CQRS: Separate Databases

**Write Database** (PostgreSQL): Normalized, ACID, single source of truth
```sql
CREATE TABLE bookings (id UUID PRIMARY KEY, user_id UUID, showtime_id UUID, status VARCHAR);
CREATE TABLE bookings_detail (booking_id UUID, seat_row INT, seat_col INT);
```

**Read Database** (Elasticsearch, PostgreSQL materialized view, etc.): Denormalized, eventual consistency
```json
{
  "id": "booking-123",
  "user_id": "user-456",
  "user_email": "john@example.com",
  "user_name": "John Doe",
  "showtime_id": "show-789",
  "movie_title": "The Matrix",
  "movie_rating": 9.2,
  "status": "confirmed",
  "seat": "5-10",
  "price": 15.99,
  "created_at": "2025-03-26T10:00:00Z"
}
```

**Flow:**
```
1. User books seat
2. BookingService writes to Write DB (PostgreSQL)
3. BookingService publishes "BookingCreated" event
4. ReadProjector subscribes to event
5. ReadProjector denormalizes: joins booking + user + showtime + movie
6. ReadProjector writes to Read DB (Elasticsearch)
7. Dashboard queries Read DB
```

**Eventual Consistency:**
```
10:00:00 - User books seat
10:00:00.1 - Write DB updated
10:00:00.2 - Event published
10:00:00.3 - Read projector receives event
10:00:00.5 - Read DB updated
10:00:00.6 - Dashboard query returns new booking

User might see stale data for 600ms, but it's guaranteed to arrive.
```

**Pros:**
- Write DB optimized for consistency
- Read DB optimized for queries
- Independent scaling
- Read failures don't affect writes

**Cons:**
- Eventual consistency: reads lag behind writes
- Operational complexity: manage two databases
- Consistency bugs: read model stale or wrong
- "Read-your-own-write" inconsistency: user writes, queries read model immediately, gets stale data

### Event Sourcing + CQRS: Maximum Flexibility

Instead of storing current state, store all events:

```
Bookings table (write DB):
  NOT stored; reconstructed from events

Booking Events (append-only log):
  ReservationCreated: {booking_id, user_id, showtime_id, created_at}
  SeatAssigned: {booking_id, seat_row, seat_col}
  PaymentProcessed: {booking_id, transaction_id, amount}
  BookingConfirmed: {booking_id, confirmed_at}
```

**Reconstruct current state by replaying events:**
```go
func GetBooking(bookingId string) *Booking {
    events := eventStore.GetEvents(bookingId)
    booking := &Booking{Id: bookingId}

    for _, event := range events {
        switch event.Type {
        case "ReservationCreated":
            booking.Status = "pending"
        case "SeatAssigned":
            booking.SeatRow = event.Data["seat_row"]
            booking.SeatCol = event.Data["seat_col"]
        case "PaymentProcessed":
            booking.TransactionId = event.Data["transaction_id"]
        case "BookingConfirmed":
            booking.Status = "confirmed"
        }
    }

    return booking
}
```

**Projections: Build read models from events**

```
Events → Projection → Read DB

ReservationCreated → projection → Elasticsearch document
SeatAssigned → projection → Elasticsearch document (update)
PaymentProcessed → projection → Elasticsearch document (update)
BookingConfirmed → projection → Elasticsearch document (update)
```

**Pros:**
- Complete audit trail (all changes)
- Temporal queries ("what was the state at 10:05?")
- Replay from any point in time
- Multiple projections for different read models

**Cons:**
- High complexity
- Performance: Must replay all events for current state (use snapshots)
- Consistency challenges: projections can diverge from events
- Difficult to evolve domain model

**When to use:**
- Regulatory requirements (finance, healthcare, auditability)
- Complex domain logic with many business rules
- Need temporal queries
- Small enough event stream that replay is feasible

**When NOT to use:**
- Most CRUD applications
- Simple domains without audit requirements
- Extremely high-throughput systems (append-only logs have limits)

## CQRS Patterns: Building Read Models

### Pattern 1: Materialized Views

PostgreSQL materialized views for read models.

**Write Model** (normalized):
```sql
CREATE TABLE bookings (id UUID PRIMARY KEY, user_id UUID, showtime_id UUID, ...);
CREATE TABLE users (id UUID PRIMARY KEY, email VARCHAR, name VARCHAR, ...);
CREATE TABLE showtimes (id UUID PRIMARY KEY, movie_id UUID, theater VARCHAR, ...);
CREATE TABLE movies (id UUID PRIMARY KEY, title VARCHAR, rating DECIMAL, ...);
```

**Materialized View** (denormalized read model):
```sql
CREATE MATERIALIZED VIEW booking_dashboard AS
SELECT
    b.id,
    b.user_id,
    u.email,
    u.name,
    b.showtime_id,
    s.movie_id,
    m.title,
    m.rating,
    b.status,
    b.created_at
FROM bookings b
JOIN users u ON b.user_id = u.id
JOIN showtimes s ON b.showtime_id = s.id
JOIN movies m ON s.movie_id = m.id;

CREATE INDEX idx_booking_dashboard_user ON booking_dashboard(user_id);
CREATE INDEX idx_booking_dashboard_created ON booking_dashboard(created_at DESC);
```

**Refresh periodically:**
```go
func RefreshReadModel(db *pgx.Conn) {
    _, err := db.Exec(context.Background(), `
        REFRESH MATERIALIZED VIEW CONCURRENTLY booking_dashboard
    `)
    // Run every 5 minutes
}
```

**Query the view:**
```go
func GetDashboardBookings(ctx context.Context, userId string) ([]Booking, error) {
    rows, _ := db.Query(ctx, `
        SELECT id, user_id, email, name, title, rating, status, created_at
        FROM booking_dashboard
        WHERE user_id = $1
        ORDER BY created_at DESC
    `, userId)
    // Parse results
}
```

**Pros:**
- Single database
- Simple to implement
- Refresh is atomic

**Cons:**
- Locks table during refresh (non-concurrent refresh)
- Stale until next refresh
- Complex materialized view queries can be slow

### Pattern 2: Event-Driven Projections

Build read models from events.

```go
type BookingProjector struct {
    writeDB *pgx.Conn      // Write model (PostgreSQL)
    readDB  *pgx.Conn      // Read model (PostgreSQL, Elasticsearch, etc.)
    logger  *zap.Logger
}

// Subscribe to events
func (bp *BookingProjector) ProcessBookingCreatedEvent(ctx context.Context, event *BookingCreatedEvent) error {
    // Fetch related data from write DB (JOINs)
    user, _ := bp.getUser(ctx, event.UserId)
    showtime, _ := bp.getShowtime(ctx, event.ShowtimeId)
    movie, _ := bp.getMovie(ctx, showtime.MovieId)

    // Build denormalized document
    doc := map[string]interface{}{
        "id": event.BookingId,
        "user_id": event.UserId,
        "user_email": user.Email,
        "user_name": user.Name,
        "showtime_id": event.ShowtimeId,
        "movie_title": movie.Title,
        "movie_rating": movie.Rating,
        "status": "pending",
        "created_at": event.CreatedAt,
    }

    // Write to read DB
    payload, _ := json.Marshal(doc)
    _, err := bp.readDB.Exec(ctx, `
        INSERT INTO booking_dashboard (id, data)
        VALUES ($1, $2)
        ON CONFLICT (id) DO UPDATE SET data = $2
    `, event.BookingId, payload)

    if err != nil {
        bp.logger.Error("Failed to project booking", zap.Error(err))
        return err
    }

    return nil
}

func (bp *BookingProjector) ProcessBookingConfirmedEvent(ctx context.Context, event *BookingConfirmedEvent) error {
    _, err := bp.readDB.Exec(ctx, `
        UPDATE booking_dashboard
        SET data = jsonb_set(data, '{status}', '"confirmed"')
        WHERE id = $1
    `, event.BookingId)
    return err
}

// Handle events from Kafka
func (bp *BookingProjector) HandleKafkaMessages(ctx context.Context) {
    reader := kafka.NewReader(kafka.ReaderConfig{
        Brokers: []string{"kafka:9092"},
        Topic: "bookings",
        GroupID: "booking-projector",
    })

    for {
        msg, _ := reader.ReadMessage(ctx)

        var event interface{}
        json.Unmarshal(msg.Value, &event)

        eventMap := event.(map[string]interface{})
        eventType := eventMap["type"].(string)

        switch eventType {
        case "ReservationCreated":
            // Unmarshal and process
        case "BookingConfirmed":
            // Unmarshal and process
        }
    }
}
```

**Pros:**
- Event-driven: automatic updates
- Loose coupling: projector is independent
- Multiple projections possible: same events, different read models

**Cons:**
- Latency: events take time to propagate
- Complexity: projector service
- Debugging: must trace events through Kafka to read model

### Pattern 3: Elasticsearch for Full-Text Search

Read model for complex queries.

**Write to Elasticsearch on event:**
```go
type ElasticsearchProjector struct {
    es *elasticsearch.Client
}

func (ep *ElasticsearchProjector) ProjectBooking(ctx context.Context, event *BookingCreatedEvent) error {
    doc := map[string]interface{}{
        "id": event.BookingId,
        "user_name": event.UserName,  // Indexed for full-text search
        "movie_title": event.MovieTitle,
        "status": "pending",
        "price": event.Price,
        "created_at": event.CreatedAt,
    }

    req := esapi.IndexRequest{
        Index: "bookings",
        DocumentID: event.BookingId,
        Body: bytes.NewReader([]byte(doc)),
    }

    res, _ := req.Do(ctx, ep.es)
    return nil
}
```

**Query Elasticsearch:**
```go
func SearchBookings(ctx context.Context, es *elasticsearch.Client, query string) ([]Booking, error) {
    req := esapi.SearchRequest{
        Index: []string{"bookings"},
        Body: bytes.NewReader([]byte(fmt.Sprintf(`{
            "query": {
                "multi_match": {
                    "query": "%s",
                    "fields": ["user_name^2", "movie_title", "status"]
                }
            }
        }`, query))),
    }

    res, _ := req.Do(ctx, es)
    // Parse results
    return bookings, nil
}
```

**Pros:**
- Full-text search
- Faceting (group by genre, rating, etc.)
- Complex queries (range, aggregations, filters)

**Cons:**
- Operational complexity: manage Elasticsearch cluster
- Eventual consistency: lag between write and search

## Production Code: Movie Booking with CQRS

Complete implementation with separate write and read models.

```go
// booking/write_model.go
package booking

import (
    "context"
    "encoding/json"
    "fmt"
    "time"

    "github.com/jackc/pgx/v5"
    "github.com/google/uuid"
)

type BookingWriteService struct {
    db *pgx.Conn
}

type CreateBookingCommand struct {
    UserId     string
    ShowtimeId string
    SeatRow    int
    SeatCol    int
}

type BookingCreatedEvent struct {
    Type       string    `json:"type"`
    BookingId  string    `json:"booking_id"`
    UserId     string    `json:"user_id"`
    ShowtimeId string    `json:"showtime_id"`
    SeatRow    int       `json:"seat_row"`
    SeatCol    int       `json:"seat_col"`
    CreatedAt  time.Time `json:"created_at"`
}

func (bws *BookingWriteService) CreateBooking(ctx context.Context, cmd *CreateBookingCommand) (string, error) {
    tx, _ := bws.db.Begin(ctx)
    defer tx.Rollback(ctx)

    bookingId := uuid.NewString()

    // Write to write model (normalized)
    _, err := tx.Exec(ctx, `
        INSERT INTO bookings (id, user_id, showtime_id, status, created_at)
        VALUES ($1, $2, $3, 'pending', NOW())
    `, bookingId, cmd.UserId, cmd.ShowtimeId)
    if err != nil {
        return "", err
    }

    // Reserve seat
    _, err = tx.Exec(ctx, `
        INSERT INTO booking_seats (booking_id, showtime_id, seat_row, seat_col)
        VALUES ($1, $2, $3, $4)
    `, bookingId, cmd.ShowtimeId, cmd.SeatRow, cmd.SeatCol)
    if err != nil {
        return "", err  // Seat already booked
    }

    // Publish domain event (to outbox)
    event := BookingCreatedEvent{
        Type:       "BookingCreated",
        BookingId:  bookingId,
        UserId:     cmd.UserId,
        ShowtimeId: cmd.ShowtimeId,
        SeatRow:    cmd.SeatRow,
        SeatCol:    cmd.SeatCol,
        CreatedAt:  time.Now(),
    }

    payload, _ := json.Marshal(event)

    _, err = tx.Exec(ctx, `
        INSERT INTO outbox (aggregate_id, event_type, payload, partition_key)
        VALUES ($1, $2, $3, $4)
    `, bookingId, "BookingCreated", payload, bookingId)

    if err != nil {
        return "", err
    }

    tx.Commit(ctx)
    return bookingId, nil
}

func (bws *BookingWriteService) ConfirmBooking(ctx context.Context, bookingId, transactionId string) error {
    _, err := bws.db.Exec(ctx, `
        UPDATE bookings
        SET status = 'confirmed', transaction_id = $1, confirmed_at = NOW()
        WHERE id = $2
    `, transactionId, bookingId)
    return err
}

// booking/read_model.go
type BookingReadService struct {
    db *pgx.Conn  // Read-optimized database
}

type BookingDetailDTO struct {
    Id           string    `json:"id"`
    UserId       string    `json:"user_id"`
    UserEmail    string    `json:"user_email"`
    UserName     string    `json:"user_name"`
    MovieTitle   string    `json:"movie_title"`
    MovieRating  float64   `json:"movie_rating"`
    Theater      string    `json:"theater"`
    SeatRow      int       `json:"seat_row"`
    SeatCol      int       `json:"seat_col"`
    Status       string    `json:"status"`
    Price        float64   `json:"price"`
    CreatedAt    time.Time `json:"created_at"`
}

type DashboardStats struct {
    TotalBookings  int64   `json:"total_bookings"`
    TotalRevenue   float64 `json:"total_revenue"`
    AvgPrice       float64 `json:"avg_price"`
    PopularMovies  []MovieStat `json:"popular_movies"`
}

type MovieStat struct {
    MovieTitle string `json:"movie_title"`
    BookingCount int64 `json:"booking_count"`
}

// Simple CQRS: Query denormalized table
func (brs *BookingReadService) GetUserBookings(ctx context.Context, userId string) ([]BookingDetailDTO, error) {
    rows, _ := brs.db.Query(ctx, `
        SELECT id, user_id, user_email, user_name, movie_title, movie_rating,
               theater, seat_row, seat_col, status, price, created_at
        FROM booking_denormalized
        WHERE user_id = $1
        ORDER BY created_at DESC
    `, userId)
    defer rows.Close()

    var bookings []BookingDetailDTO
    for rows.Next() {
        var b BookingDetailDTO
        rows.Scan(&b.Id, &b.UserId, &b.UserEmail, &b.UserName, &b.MovieTitle,
            &b.MovieRating, &b.Theater, &b.SeatRow, &b.SeatCol, &b.Status, &b.Price, &b.CreatedAt)
        bookings = append(bookings, b)
    }

    return bookings, nil
}

func (brs *BookingReadService) GetDashboardStats(ctx context.Context) (*DashboardStats, error) {
    // Use pre-computed aggregates
    var stats DashboardStats

    // Get totals
    brs.db.QueryRow(ctx, `
        SELECT COUNT(*), SUM(price), AVG(price)
        FROM booking_denormalized
        WHERE created_at > NOW() - INTERVAL 24 HOURS
    `).Scan(&stats.TotalBookings, &stats.TotalRevenue, &stats.AvgPrice)

    // Get top movies
    rows, _ := brs.db.Query(ctx, `
        SELECT movie_title, COUNT(*) as booking_count
        FROM booking_denormalized
        WHERE created_at > NOW() - INTERVAL 24 HOURS
        GROUP BY movie_title
        ORDER BY booking_count DESC
        LIMIT 10
    `)

    var popularMovies []MovieStat
    for rows.Next() {
        var m MovieStat
        rows.Scan(&m.MovieTitle, &m.BookingCount)
        popularMovies = append(popularMovies, m)
    }

    stats.PopularMovies = popularMovies

    return &stats, nil
}

// booking/read_projector.go
type BookingReadProjector struct {
    writeDB *pgx.Conn
    readDB  *pgx.Conn
}

func (brp *BookingReadProjector) ProjectBookingCreated(ctx context.Context, event *BookingCreatedEvent) error {
    // Fetch from write model to get all data
    var userEmail, userName, movieTitle string
    var movieRating float64
    var theater string
    var price float64

    err := brp.writeDB.QueryRow(ctx, `
        SELECT u.email, u.name, m.title, m.rating, s.theater, s.price
        FROM bookings b
        JOIN users u ON b.user_id = u.id
        JOIN showtimes s ON b.showtime_id = s.id
        JOIN movies m ON s.movie_id = m.id
        WHERE b.id = $1
    `, event.BookingId).Scan(&userEmail, &userName, &movieTitle, &movieRating, &theater, &price)

    if err != nil {
        return err
    }

    // Write denormalized record to read DB
    _, err = brp.readDB.Exec(ctx, `
        INSERT INTO booking_denormalized
        (id, user_id, user_email, user_name, movie_title, movie_rating,
         theater, seat_row, seat_col, status, price, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'pending', $10, $11)
    `, event.BookingId, event.UserId, userEmail, userName, movieTitle, movieRating,
       theater, event.SeatRow, event.SeatCol, price, event.CreatedAt)

    return err
}

func (brp *BookingReadProjector) ProjectBookingConfirmed(ctx context.Context, event *BookingConfirmedEvent) error {
    _, err := brp.readDB.Exec(ctx, `
        UPDATE booking_denormalized
        SET status = 'confirmed'
        WHERE id = $1
    `, event.BookingId)
    return err
}
```

### Database Schemas

```sql
-- Write Model (normalized, transactional)
CREATE TABLE bookings (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    showtime_id UUID NOT NULL,
    transaction_id VARCHAR,
    status VARCHAR(50),
    created_at TIMESTAMP,
    confirmed_at TIMESTAMP
);

CREATE TABLE booking_seats (
    booking_id UUID NOT NULL,
    showtime_id UUID NOT NULL,
    seat_row INT,
    seat_col INT,
    PRIMARY KEY (booking_id, showtime_id, seat_row, seat_col)
);

CREATE TABLE users (
    id UUID PRIMARY KEY,
    email VARCHAR UNIQUE,
    name VARCHAR
);

CREATE TABLE showtimes (
    id UUID PRIMARY KEY,
    movie_id UUID,
    theater VARCHAR,
    price DECIMAL
);

CREATE TABLE movies (
    id UUID PRIMARY KEY,
    title VARCHAR,
    rating DECIMAL
);

-- Read Model (denormalized, optimized for queries)
CREATE TABLE booking_denormalized (
    id UUID PRIMARY KEY,
    user_id UUID,
    user_email VARCHAR,
    user_name VARCHAR,
    movie_title VARCHAR,
    movie_rating DECIMAL,
    theater VARCHAR,
    seat_row INT,
    seat_col INT,
    status VARCHAR(50),
    price DECIMAL,
    created_at TIMESTAMP
);

-- Indexes for read queries
CREATE INDEX idx_denorm_user ON booking_denormalized(user_id, created_at DESC);
CREATE INDEX idx_denorm_movie ON booking_denormalized(movie_title);
CREATE INDEX idx_denorm_created ON booking_denormalized(created_at DESC);
```

## Trade-offs & Anti-Patterns

### What Breaks

**1. Projection Lag**
```
User books seat (10:00:00)
Write model updated (10:00:00.1)
Event published (10:00:00.2)
Projector gets event (10:00:00.4)
Read model updated (10:00:00.6)
User queries dashboard, sees old data (10:00:00.5)
```

Fix: Make users aware of eventual consistency. Show "refreshing..." or use real-time updates (WebSocket).

**2. Split Brain**
```
Write model: Booking confirmed
Read model: Booking pending (projector crashed before update)
Different services see different state
```

Fix: Projector error handling. Retry failed updates. Periodic consistency checks.

**3. Over-Engineering Simple Domains**
```
You have a simple CRUD app with one entity
You implement full CQRS with event sourcing
Now you have 10 services, eventual consistency bugs, replay latency
```

Fix: Start with simple CQRS (same DB, different models). Use full CQRS only when you need it.

**4. Read Model Growing Stale**
```
Dashboard shows booking count from yesterday
Queries are expensive and run once per day
Users see outdated metrics
```

Fix: Refresh read model more frequently. Add materialized view refresh on write.

**5. Consistency During Projector Failure**
```
Projector down for 2 hours
50,000 events queued
When it comes back, it's way behind
Users see very stale reads
```

Fix: Add circuit breaker to projector. If too far behind, trigger a full rebuild of read model.

## Interview Corner

**Q1: When should you use CQRS vs. a simple read replica?**

A: **Read replica** (same schema):
- Suitable for applications where read and write access patterns are similar
- Lower complexity
- Consistency is easier (eventual consistency on replica)

**CQRS** (different schemas):
- Needed when read and write patterns are vastly different (different fields, different aggregations)
- Write model optimized for transactions, read model for queries
- Complexity is worth it for performance

Use read replica first. Move to CQRS if one of the models bottlenecks.

**Q2: What's the difference between simple CQRS and full CQRS with event sourcing?**

A: **Simple CQRS**: Same database, different tables or views.
- Write: `bookings` table (normalized)
- Read: `booking_dashboard` view or table (denormalized)
- Both in same DB, updated together

**Full CQRS + Event Sourcing**: Separate databases, events drive updates.
- Write: Event log (PostgreSQL, event store)
- Read: Elasticsearch, materialized table
- Projector subscribes to events, updates read model
- Eventual consistency between write and read

Full CQRS is more complex but gives you complete audit trail and multiple read models.

**Q3: How do you handle "read your own write" consistency in CQRS?**

A: User writes a booking, immediately queries read model, doesn't see it.

Solutions:
1. **Write through write model**: Query the write model immediately after write, don't go to read model
2. **Request-based consistency**: Return the written booking ID, user polls for confirmation
3. **WebSocket push**: Projector sends update via WebSocket as soon as read model updated
4. **Synchronous projection**: Make projection synchronous (slower writes)

Best: Combination of #1 and #3.

**Q4: Design CQRS for WhatsApp messaging (millions of messages/second).**

A:
**Write Model**:
- PostgreSQL: messages table (immutable append-only)
- One row per message, indexed by (receiver_id, created_at)

**Read Models**:
1. **Message List** (Elasticsearch):
   - Denormalized: {message_id, sender_id, sender_name, sender_avatar, text, timestamp}
   - Indexed for search
   - Projected from events

2. **Message Stats** (Redis):
   - Total unread count per user
   - Updated on write (synchronously)

3. **Archive** (S3 + Elasticsearch):
   - Old messages (older than 6 months)
   - Searchable but read-only

Flow: User sends message → Write to PostgreSQL → Publish to Kafka → Elasticsearch projector → Update Elasticsearch → User retrieves from Elasticsearch.

**Q5: How do you version projections when domain model changes?**

A: Example: Add new field "sender_avatar_url" to messages.

Solution: Projection versioning
```go
const CurrentProjectionVersion = 2

func ProjectMessage(event *MessageSentEvent) {
    if event.ProjectionVersion < 2 {
        // Old schema, add avatar_url
        event.SenderAvatarUrl = getUserAvatar(event.SenderId)
    }
    // Write to read model
}

// Or rebuild entire read model with new schema:
func RebuildProjection() {
    // Drop old Elasticsearch index
    // Replay all events from event log
    // Project with new schema
    // Swap index
}
```

## Exercise

**Build a movie booking system with CQRS:**

1. **Write model** (PostgreSQL, normalized):
   - `bookings`, `users`, `showtimes`, `movies` tables
   - Implement CreateBooking command (write to write model)

2. **Read model** (PostgreSQL, denormalized):
   - `booking_denormalized` table
   - Implement BookingReadService (queries only)

3. **Synchronization**:
   - On CreateBooking, publish event to outbox
   - Implement projector that denormalizes on event
   - Test: Create booking, verify read model updated within 1 second

4. **Dashboard**:
   - Implement GetDashboardStats (uses pre-computed aggregates from read model)
   - Implement GetUserBookings (uses denormalized table)

5. **Consistency test**:
   - Simulate projector delay (sleep before updating read model)
   - User creates booking, immediately queries
   - Verify eventual consistency (returns within acceptable time)

Bonus:
- Implement multiple read models (Elasticsearch for search, Redis for counts)
- Implement projection versioning (add new field, rebuild)
- Implement projector error handling (DLQ for failed projections)

## Advanced CQRS Patterns

### Projection State Machines

Projections can have multiple states to handle out-of-order events:

```go
type ProjectionState struct {
    Id              string
    Version         int64  // Event version
    State           map[string]interface{}
    PendingEvents   []Event
}

func (ps *ProjectionState) ApplyEvent(event Event) error {
    // Check if event is out of order
    if event.Version != ps.Version+1 {
        if event.Version > ps.Version+1 {
            // Future event, queue it
            ps.PendingEvents = append(ps.PendingEvents, event)
            return nil
        }
        // Old event, ignore (already processed)
        return nil
    }

    // Apply event to state
    switch event.Type {
    case "BookingCreated":
        ps.State["status"] = "pending"
        ps.State["created_at"] = event.Timestamp
    case "BookingConfirmed":
        ps.State["status"] = "confirmed"
    }

    ps.Version = event.Version

    // Try to apply any pending events
    for len(ps.PendingEvents) > 0 && ps.PendingEvents[0].Version == ps.Version+1 {
        nextEvent := ps.PendingEvents[0]
        ps.PendingEvents = ps.PendingEvents[1:]
        ps.ApplyEvent(nextEvent)
    }

    return nil
}
```

### Polyglot Persistence: Multiple Read Databases

Different read models for different use cases:

```
Write DB: PostgreSQL (normalized)
  ↓
Events published to Kafka
  ↓
Projectors:
  1. PostgreSQL denormalized table (operational queries)
  2. Elasticsearch (full-text search)
  3. Redis (counts, caching)
  4. S3 (archive, cold storage)
```

**Configuration:**
```go
type MultiStoreProjector struct {
    postgres  *pgx.Conn
    es        *elasticsearch.Client
    redis     *redis.Client
    s3        *s3.Client
}

func (msp *MultiStoreProjector) ProjectBookingCreated(ctx context.Context, event *BookingCreatedEvent) error {
    // PostgreSQL: denormalized for operational queries
    err1 := msp.projectToPostgres(ctx, event)

    // Elasticsearch: for search
    err2 := msp.projectToElasticsearch(ctx, event)

    // Redis: for counts
    err3 := msp.projectToRedis(ctx, event)

    // S3: for archival (async)
    go msp.projectToS3(context.Background(), event)

    // If all succeed, great. If some fail, depends on criticality.
    if err1 != nil {
        log.Printf("Failed to project to PostgreSQL: %v", err1)
        // This is critical, return error (DLQ for retry)
        return err1
    }

    if err2 != nil || err3 != nil {
        log.Printf("Non-critical projection failed (ES or Redis)")
        // Could log to DLQ for later repair, but don't fail here
    }

    return nil
}
```

**Use-case specific reads:**

```go
// Operational dashboard: Query PostgreSQL
func GetUserBookings(userId string) ([]Booking, error) {
    return postgres.Query("SELECT * FROM booking_denormalized WHERE user_id = $1", userId)
}

// Search: Query Elasticsearch
func SearchBookings(query string) ([]SearchResult, error) {
    return es.Search(query)
}

// Counts: Query Redis (cached)
func GetTotalBookingCount() (int, error) {
    return redis.Get("booking_count_total").Int()
}

// Analytics: Query S3 (daily aggregates)
func GetWeeklyStats() (*Stats, error) {
    return s3.GetObject("analytics/2025-03-26.json").Parse()
}
```

### Consistency Zones: Bounded Eventual Consistency

Instead of "eventually consistent" (unlimited time), define consistency guarantees:

```go
type ConsistencyZone struct {
    MaxLagSeconds int  // Max time for read model to lag write model
}

// Zone 1: Critical (payments, confirmations)
criticalZone := &ConsistencyZone{MaxLagSeconds: 100}  // 100ms lag acceptable

// Zone 2: Important (inventory, availability)
importantZone := &ConsistencyZone{MaxLagSeconds: 5}    // 5 seconds lag

// Zone 3: Nice-to-have (analytics, recommendations)
niceToHaveZone := &ConsistencyZone{MaxLagSeconds: 300}  // 5 minutes

// Implementation
func (cz *ConsistencyZone) WaitForConsistency(ctx context.Context) error {
    deadline := time.Now().Add(time.Duration(cz.MaxLagSeconds) * time.Second)

    for {
        lag := GetProjectionLag()
        if lag <= 0 {
            return nil  // Caught up
        }

        if time.Now().After(deadline) {
            return fmt.Errorf("consistency guarantee violated: %dms lag", lag)
        }

        time.Sleep(100 * time.Millisecond)
    }
}

// Usage
if err := criticalZone.WaitForConsistency(ctx); err != nil {
    return nil, err  // Don't return stale data for critical operations
}

bookings, _ := getFromReadModel()
return bookings, nil
```

### Handling Projector Failures and Rebuilds

**Scenario 1: Add new field to read model**
```
Schema change: Add "customer_phone" to booking_denormalized
But 1M existing bookings don't have it

Options:
1. Backfill: Run SQL UPDATE on 1M rows (slow)
2. Replay: Replay all events, rebuild entire read model (very slow)
3. Hybrid: Backfill from write model, then project new events
```

**Implementation:**
```go
func BackfillMissingField(ctx context.Context, writeDB, readDB *pgx.Conn) error {
    // Get all bookings that need backfill
    rows, _ := writeDB.Query(ctx, `
        SELECT b.id, u.phone
        FROM bookings b
        JOIN users u ON b.user_id = u.id
        WHERE b.id NOT IN (SELECT id FROM booking_denormalized WHERE phone IS NOT NULL)
    `)

    for rows.Next() {
        var id, phone string
        rows.Scan(&id, &phone)

        // Update read model
        readDB.Exec(ctx, "UPDATE booking_denormalized SET phone = $1 WHERE id = $2", phone, id)
    }

    return nil
}

// Then project new events normally
func ProjectBookingWithNewField(ctx context.Context, event *BookingCreatedEvent) error {
    // New bookings get the field
    readDB.Exec(ctx, `
        INSERT INTO booking_denormalized (id, user_id, ..., phone)
        VALUES ($1, $2, ..., $3)
    `, event.BookingId, event.UserId, event.UserPhone)
}
```

**Scenario 2: Projector crashes for 2 hours**

```go
func RecoverProjector(ctx context.Context, lastProcessedVersion int64) error {
    // Get all events since last processed
    events, _ := eventStore.GetEventsSince(lastProcessedVersion)

    if len(events) > 100000 {
        // Too many events to replay, rebuild read model
        return RebuildReadModel(ctx)
    }

    // Replay events
    for _, event := range events {
        ProjectEvent(ctx, event)
    }

    return nil
}

func RebuildReadModel(ctx context.Context) error {
    // Create new table with suffix
    newTableName := "booking_denormalized_2025_03_26_101500"
    createTable(newTableName)

    // Replay all events
    allEvents := eventStore.GetAllEvents()
    for _, event := range allEvents {
        ProjectEventToTable(ctx, event, newTableName)
    }

    // Atomically swap tables (rename)
    db.Exec(ctx, fmt.Sprintf("ALTER TABLE booking_denormalized RENAME TO booking_denormalized_old"))
    db.Exec(ctx, fmt.Sprintf("ALTER TABLE %s RENAME TO booking_denormalized", newTableName))

    // Can drop old table after verification
    return nil
}
```

## Advanced Interview Questions

**Q7: You have 50 read models, one projector per read model. A projector crashes. How do you prevent data loss?**

A: Several strategies:

1. **Projection checkpoints**:
   ```go
   // Save progress every 1000 events
   if eventCount % 1000 == 0 {
       db.Exec("INSERT INTO projection_checkpoint (projector_id, version) VALUES ($1, $2)",
           projectorId, eventVersion)
   }

   // On restart, resume from checkpoint
   lastVersion := getLastCheckpoint(projectorId)
   events := eventStore.GetEventsSince(lastVersion)
   ```

2. **Projector heartbeat**:
   ```go
   // Every projector sends heartbeat every 10 seconds
   tick := time.NewTicker(10 * time.Second)
   defer tick.Stop()

   for range tick.C {
       db.Exec("UPDATE projector_heartbeat SET last_seen = NOW() WHERE projector_id = $1", projectorId)
   }

   // Monitor: If no heartbeat for 30 seconds, alert
   ```

3. **Dead letter queue (DLQ)**:
   ```go
   // If projector fails on an event, send to DLQ
   for {
       event := kafka.ReadMessage()
       if err := project(event); err != nil {
           dlq.Send(event)
           metrics.ProjectionErrors.Inc()
           continue  // Don't ack, move to DLQ
       }
       kafka.CommitMessage()  // Ack only if successful
   }
   ```

4. **Multiple replicas**:
   ```go
   // Run 2-3 copies of each projector
   // Idempotent projections ensure consistency
   // If one crashes, others continue
   ```

**Q8: Design CQRS for a real-time analytics system (1M events/second).**

A: At 1M events/sec, traditional projections won't work (too slow). Solution: **Time-series CQRS**

1. **Write model**: Time-series database optimized for writes (InfluxDB, TimescaleDB)
   ```go
   // Write events as time-series data points
   measurement: "booking_events"
   tags: {showtime_id, user_id, region}
   fields: {amount, duration_ms}
   timestamp: event.CreatedAt
   ```

2. **Read model**: Pre-aggregated at different time windows
   ```
   Raw (1M/sec) → 1-minute aggregates → 1-hour aggregates → 1-day aggregates
   ```
   Use materialized views or CQRS stream processors

3. **Projection strategy**:
   ```go
   // Don't project each event individually
   // Batch events (every 1 second = 1M events)
   // Aggregate in batch, write summary

   if len(batch) % 1000000 == 0 {
       agg := AggregateEvents(batch)
       writeToTimeseries(agg)
   }
   ```

4. **Query pattern**: Always query aggregates, never raw events
   ```go
   // Query 1-minute aggregate
   SELECT SUM(amount), COUNT(*) FROM bookings_1m WHERE time >= NOW() - INTERVAL 1 HOUR

   // NOT: SELECT * FROM raw_events (would scan 60M events)
   ```

**Q9: Your read model is stale by 10 minutes. Users are complaining. How do you diagnose?**

A: Checklist:

1. **Check projector lag**:
   ```sql
   SELECT MAX(event_timestamp) FROM event_log;  -- 10:00:00
   SELECT MAX(updated_at) FROM booking_denormalized;  -- 09:50:00
   -- Lag is 10 minutes
   ```

2. **Check projector process**:
   ```
   - Is projector running? ps aux | grep projector
   - Is it consuming events? Check Kafka offset
   - Is it updating read DB? Check query logs
   ```

3. **Measure throughput**:
   ```sql
   SELECT COUNT(*) FROM event_log WHERE event_timestamp > NOW() - INTERVAL 1 MINUTE;  -- 10k events/min

   SELECT COUNT(*) FROM event_log WHERE processed = true AND processed_at > NOW() - INTERVAL 1 MINUTE;  -- 5k events/min

   -- Lag is growing because projector can't keep up
   ```

4. **Fix options**:
   - **Quick**: Scale up projector (more CPU/memory)
   - **Medium**: Add more projector instances (parallel processing)
   - **Fundamental**: Switch to faster read model (Redis instead of PostgreSQL)
   - **Nuclear**: Rebuild read model from scratch


