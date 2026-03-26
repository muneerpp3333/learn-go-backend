# The Outbox Pattern: Exactly-Once Event Publishing

## The Problem: The Dual-Write Dilemma

You're in BookingService. User books a seat. You need to:

1. Update the `bookings` table
2. Publish a `ReservationCreated` event to Kafka

**Naive approach:**
```go
// Step 1: Update database
db.Exec("INSERT INTO bookings ...")

// Step 2: Publish event
kafka.Publish("reservation.created", event)
```

**What happens if Kafka is down?**
```
Step 1: Complete (booking created)
Step 2: Fails (Kafka unavailable)
Result: Booking exists but downstream services (payment, notification) don't know about it
```

**What if you reverse the order?**
```go
// Step 1: Publish event
kafka.Publish("reservation.created", event)

// Step 2: Update database
db.Exec("INSERT INTO bookings ...")
```

**If DB fails:**
```
Step 1: Complete (event published)
Step 2: Fails (DB error)
Result: Event processed, booking never created. Inconsistent state.
```

**The core problem**: Database and message queue are separate systems. You can't atomically write to both. If one succeeds and the other fails, you're stuck.

This is called the **dual-write problem**.

## Theory: The Transactional Outbox

The solution: Write the event to the *same database* as your business data.

**Instead of:**
```
BookingService:
  1. Write to bookings table
  2. Write to Kafka

PaymentService:
  1. Read from Kafka
  2. Write to transactions table
```

**Do this:**
```
BookingService:
  1. Write to bookings table
  2. Write to outbox table (same transaction!)

Outbox Poller (background job):
  1. Poll outbox table for unpublished events
  2. Publish to Kafka
  3. Mark as published

PaymentService:
  1. Read from Kafka
  2. Write to transactions table AND inbox table (same transaction!)

Inbox Processor (background job):
  1. Process events from inbox
  2. Ensure idempotency (don't process same event twice)
```

### Outbox Table Schema

```sql
CREATE TABLE outbox (
    id BIGSERIAL PRIMARY KEY,
    aggregate_id UUID NOT NULL,           -- e.g., booking_id
    event_type VARCHAR(255) NOT NULL,    -- e.g., "ReservationCreated"
    payload JSONB NOT NULL,              -- serialized event
    created_at TIMESTAMP DEFAULT NOW(),
    published_at TIMESTAMP NULL,
    retry_count INT DEFAULT 0,
    partition_key VARCHAR(255)           -- for ordering (e.g., booking_id)
);

CREATE INDEX idx_outbox_published_at ON outbox(published_at, created_at);
CREATE INDEX idx_outbox_partition ON outbox(partition_key, created_at);
```

**Key columns:**
- `aggregate_id`: Links event to the business entity (booking, user, etc.)
- `event_type`: What happened (ReservationCreated, ReservationCancelled)
- `payload`: The event data as JSON
- `published_at`: NULL until event is published. Once published, never NULL.
- `partition_key`: Ensures all events for a booking are published in order (if using partitioned Kafka topic)

### Writing to the Outbox

The critical part: booking + outbox write happen in the *same transaction*.

```go
func (s *BookingService) CreateBooking(ctx context.Context, req *CreateBookingRequest) error {
    tx, _ := s.db.Begin(ctx)
    defer tx.Rollback(ctx)

    // Step 1: Insert booking
    var bookingId string
    err := tx.QueryRow(ctx, `
        INSERT INTO bookings (user_id, showtime_id, status, created_at)
        VALUES ($1, $2, 'pending', NOW())
        RETURNING id
    `, req.UserId, req.ShowtimeId).Scan(&bookingId)

    if err != nil {
        return err
    }

    // Step 2: Insert to outbox (SAME TRANSACTION)
    event := map[string]interface{}{
        "booking_id": bookingId,
        "user_id": req.UserId,
        "showtime_id": req.ShowtimeId,
        "created_at": time.Now(),
    }

    payload, _ := json.Marshal(event)

    _, err = tx.Exec(ctx, `
        INSERT INTO outbox (aggregate_id, event_type, payload, partition_key, created_at)
        VALUES ($1, $2, $3, $4, NOW())
    `, bookingId, "ReservationCreated", payload, bookingId)

    if err != nil {
        return err
    }

    // Step 3: Commit both writes atomically
    return tx.Commit(ctx)
}
```

**Why this works:**
- If the database crashes after writing both rows, both exist
- If the database crashes after writing booking but before outbox, booking exists but no event; outbox poller will never see it
- The outbox poller is responsible for eventually publishing the event

Wait, there's a gap: what if the database crashes between the booking write and the outbox write?

**In practice**, this gap is microseconds. PostgreSQL's write-ahead log (WAL) ensures atomicity at the micro level. But theoretically, you could have:
- Booking inserted
- Database crashes
- Outbox insert lost

**Mitigation:** Ensure your outbox polling is frequent (every 5-10 seconds) and your booking creation is idempotent. If the user retries with the same booking ID, they get the same result.

### Outbox Polling: Publishing Events

A background goroutine periodically polls the outbox table for unpublished events.

```go
type OutboxPublisher struct {
    db       *pgx.Conn
    producer *kafka.Producer
}

func (op *OutboxPublisher) PollAndPublish(ctx context.Context) error {
    // Poll unpublished events
    rows, _ := op.db.Query(ctx, `
        SELECT id, aggregate_id, event_type, payload, partition_key
        FROM outbox
        WHERE published_at IS NULL
        ORDER BY created_at ASC
        LIMIT 100
        FOR UPDATE SKIP LOCKED  -- Important: Skip locked rows (other pollers)
    `)
    defer rows.Close()

    var published []int64

    for rows.Next() {
        var id int64
        var aggregateId, eventType, partitionKey string
        var payload []byte

        rows.Scan(&id, &aggregateId, &eventType, &payload, &partitionKey)

        // Publish to Kafka
        err := op.producer.Produce(&kafka.Message{
            TopicPartition: kafka.TopicPartition{
                Topic: &eventType,  // Topic name = event type (e.g., "ReservationCreated")
                Partition: kafka.PartitionAny,
            },
            Key: []byte(partitionKey),  // Partition key ensures ordering
            Value: payload,
        }, nil)

        if err != nil {
            log.Printf("Failed to publish event %d: %v", id, err)
            continue  // Don't mark as published
        }

        published = append(published, id)
    }

    // Mark as published (only successful publishes)
    if len(published) > 0 {
        op.markPublished(ctx, published)
    }

    return nil
}

func (op *OutboxPublisher) markPublished(ctx context.Context, ids []int64) {
    // Convert slice to SQL array
    _, _ = op.db.Exec(ctx, `
        UPDATE outbox
        SET published_at = NOW()
        WHERE id = ANY($1)
    `, ids)
}

// Run in a goroutine
func (op *OutboxPublisher) Start(ctx context.Context) {
    ticker := time.NewTicker(5 * time.Second)  // Poll every 5 seconds
    defer ticker.Stop()

    for {
        select {
        case <-ticker.C:
            op.PollAndPublish(ctx)
        case <-ctx.Done():
            return
        }
    }
}
```

### FOR UPDATE SKIP LOCKED: Concurrent Polling

Multiple outbox pollers might run simultaneously. The `FOR UPDATE SKIP LOCKED` clause ensures each row is processed once:

```sql
SELECT id, aggregate_id, event_type, payload, partition_key
FROM outbox
WHERE published_at IS NULL
ORDER BY created_at ASC
LIMIT 100
FOR UPDATE SKIP LOCKED;
```

**What it does:**
1. `FOR UPDATE`: Lock the rows
2. `SKIP LOCKED`: Skip any rows already locked by another poller

Result: Two pollers can't process the same event.

### Polling Interval Trade-offs

**Faster polling (1 second):**
- Pro: Events reach downstream services quickly (low latency)
- Con: Higher database load, more unnecessary queries

**Slower polling (30 seconds):**
- Pro: Lower database load
- Con: Events take longer to propagate (high latency)

**Recommendation:** 5-10 seconds. On busy systems, every poll will find events, so the overhead is minimal.

### Change Data Capture (CDC): Alternative to Polling

Instead of polling, use **CDC** to stream changes from the database's transaction log.

**Tools:** Debezium, Postgres WAL tailing, MySQL binlog, etc.

**How it works:**
```
PostgreSQL WAL (Write-Ahead Log)
  ↓
Debezium (captures changes)
  ↓
Kafka (streams to PaymentService, NotificationService)
```

**Advantages:**
- Latency: Events published milliseconds after write (vs. polling delay)
- Load: No repeated queries to the same table
- Ordering: Guaranteed ordering per partition

**Disadvantages:**
- Operational complexity: Need to run and maintain Debezium
- Exact-once delivery still requires idempotency on consumer side
- Requires access to the database's transaction log

**When to use CDC:**
- High-volume events (millions/second)
- Latency-critical applications
- You have the ops team to run it

**When to use polling:**
- Starting out
- Low-to-medium volume
- Simplicity is a priority

## Inbox Pattern: Consuming Events Idempotently

The outbox pattern ensures events are published. But what if a consumer processes the same event twice?

```
PaymentService receives "ReservationCreated" event
Processes payment, writes to database
Acknowledgement is sent to Kafka, but network fails
Kafka retransmits the event
PaymentService processes again, charges customer twice
```

**Solution: Inbox pattern.** Every consumer maintains an `inbox` table.

```sql
CREATE TABLE inbox (
    id BIGSERIAL PRIMARY KEY,
    event_id VARCHAR(255) UNIQUE NOT NULL,  -- From upstream outbox
    event_type VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',   -- pending, processed, failed
    processed_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_inbox_status ON inbox(status, created_at);
CREATE INDEX idx_inbox_event_id ON inbox(event_id);
```

**Idempotent consumption:**

```go
func (s *PaymentService) ProcessReservationCreated(ctx context.Context, event *ReservationCreatedEvent) error {
    // Step 1: Check if we've already processed this event
    var existingStatus string
    err := s.db.QueryRow(ctx, `
        SELECT status FROM inbox WHERE event_id = $1
    `, event.EventId).Scan(&existingStatus)

    if err == nil && existingStatus == "processed" {
        log.Printf("Event %s already processed, skipping", event.EventId)
        return nil  // Idempotent: return success
    }

    // Step 2: Start transaction
    tx, _ := s.db.Begin(ctx)
    defer tx.Rollback(ctx)

    // Step 3: Insert into inbox (or skip if already exists)
    _, _ = tx.Exec(ctx, `
        INSERT INTO inbox (event_id, event_type, payload, status)
        VALUES ($1, $2, $3, 'pending')
        ON CONFLICT (event_id) DO NOTHING
    `, event.EventId, event.Type, event.Payload)

    // Step 4: Process the business logic (charge card)
    transactionId, err := s.chargeCard(ctx, event.UserId, event.Amount)
    if err != nil {
        return err
    }

    // Step 5: Write business data and mark inbox as processed (SAME TRANSACTION)
    _, _ = tx.Exec(ctx, `
        INSERT INTO transactions (booking_id, user_id, amount, status)
        VALUES ($1, $2, $3, 'completed')
    `, event.BookingId, event.UserId, event.Amount)

    _, _ = tx.Exec(ctx, `
        UPDATE inbox SET status = 'processed', processed_at = NOW() WHERE event_id = $1
    `, event.EventId)

    return tx.Commit(ctx)
}
```

**Key insight:** The inbox and business data writes happen in the same transaction. Either both succeed or both fail.

## Ordering Guarantees: Partition Keys

By default, Kafka doesn't guarantee global ordering. Events can be processed out of order:

```
Event 1: Reservation created
Event 2: Reservation confirmed
Events might process as: 2, 1 (confirmation before creation)
```

**Solution: Partition keys.**

When publishing to Kafka, use the same partition key for all events related to an entity:

```go
// OutboxPublisher
kafka.Message{
    Topic: "ReservationCreated",
    Key: []byte(booking_id),  // Same key = same partition = ordered
    Value: payload,
}
```

All events for booking_id "booking-123" go to the same partition. Kafka guarantees order within a partition.

## Delivery Guarantees

### At-Least-Once Delivery

The outbox publisher publishes the event, waits for Kafka acknowledgement, then marks as published. If Kafka ack is delayed, the event might be published twice.

```
Outbox Publisher publishes event to Kafka
Kafka acks
Network failure (ack lost)
Outbox Publisher times out, republishes
Kafka now has 2 copies of the event
```

**Mitigation:** Idempotent consumers (inbox pattern).

### Exactly-Once Delivery (Practically)

Use outbox + inbox + idempotency keys. Not truly exactly-once (that requires atomic writes across two databases), but achieves the same result:

```
Outbox: Write booking + event in same transaction (at-least-once from DB perspective)
Kafka: Transmits event to PaymentService
Inbox: Deduplicate using event_id (idempotent processing)
Result: Despite potential duplicates, PaymentService processes only once
```

### At-Most-Once Delivery

Publish event, don't wait for Kafka ack, mark as published immediately.

```go
kafka.Produce(&message, nil)  // Non-blocking, no ack waiting
db.Exec("UPDATE outbox SET published_at = NOW() WHERE id = $1", id)
```

**Problems:** Events can be lost if Kafka fails.

**Use case:** Non-critical events (analytics, metrics).

## Production Code: Complete Outbox + Inbox

Full movie booking implementation with exact-once semantics.

```go
// booking-service/outbox.go
package booking

import (
    "context"
    "encoding/json"
    "log"
    "time"

    "github.com/jackc/pgx/v5"
)

type ReservationCreatedEvent struct {
    EventId     string                 `json:"event_id"`
    BookingId   string                 `json:"booking_id"`
    UserId      string                 `json:"user_id"`
    ShowtimeId  string                 `json:"showtime_id"`
    SeatRow     int                    `json:"seat_row"`
    SeatCol     int                    `json:"seat_col"`
    CreatedAt   time.Time              `json:"created_at"`
}

type BookingService struct {
    db *pgx.Conn
}

func (s *BookingService) CreateBooking(ctx context.Context, req *CreateBookingRequest) (string, error) {
    tx, _ := s.db.Begin(ctx)
    defer tx.Rollback(ctx)

    // Step 1: Create booking
    bookingId := uuid.NewString()
    _, err := tx.Exec(ctx, `
        INSERT INTO bookings (id, user_id, showtime_id, status, created_at)
        VALUES ($1, $2, $3, 'pending', NOW())
    `, bookingId, req.UserId, req.ShowtimeId)
    if err != nil {
        return "", err
    }

    // Step 2: Insert into outbox (SAME TRANSACTION)
    eventId := uuid.NewString()
    event := ReservationCreatedEvent{
        EventId:    eventId,
        BookingId:  bookingId,
        UserId:     req.UserId,
        ShowtimeId: req.ShowtimeId,
        SeatRow:    req.SeatRow,
        SeatCol:    req.SeatCol,
        CreatedAt:  time.Now(),
    }

    payload, _ := json.Marshal(event)

    _, err = tx.Exec(ctx, `
        INSERT INTO outbox (aggregate_id, event_type, payload, partition_key, created_at)
        VALUES ($1, $2, $3, $4, NOW())
    `, bookingId, "ReservationCreated", payload, bookingId)

    if err != nil {
        return "", err
    }

    // Step 3: Commit atomically
    if err = tx.Commit(ctx); err != nil {
        return "", err
    }

    log.Printf("Booking created: %s, event %s queued to outbox", bookingId, eventId)
    return bookingId, nil
}

// OutboxPublisher: Background goroutine that publishes events
type OutboxPublisher struct {
    db       *pgx.Conn
    producer *kafka.Producer  // Kafka client
}

func (op *OutboxPublisher) PollAndPublish(ctx context.Context) error {
    // Query unpublished events with FOR UPDATE SKIP LOCKED
    rows, _ := op.db.Query(ctx, `
        SELECT id, aggregate_id, event_type, payload, partition_key
        FROM outbox
        WHERE published_at IS NULL
        ORDER BY created_at ASC
        LIMIT 100
        FOR UPDATE SKIP LOCKED
    `)
    defer rows.Close()

    var successIds []int64

    for rows.Next() {
        var id int64
        var aggregateId, eventType, partitionKey string
        var payload []byte

        rows.Scan(&id, &aggregateId, &eventType, &payload, &partitionKey)

        // Publish to Kafka
        deliveryChan := make(chan kafka.Event, 1)
        err := op.producer.Produce(&kafka.Message{
            TopicPartition: kafka.TopicPartition{
                Topic: &eventType,
                Partition: kafka.PartitionAny,
            },
            Key: []byte(partitionKey),
            Value: payload,
        }, deliveryChan)

        if err != nil {
            log.Printf("Failed to publish event %d: %v", id, err)
            continue
        }

        // Wait for delivery confirmation
        e := <-deliveryChan
        m := e.(*kafka.Message)

        if m.TopicPartition.Error != nil {
            log.Printf("Failed to deliver event %d: %v", id, m.TopicPartition.Error)
            continue
        }

        log.Printf("Event published: %s (partition %d, offset %d)", eventType, m.TopicPartition.Partition, m.TopicPartition.Offset)
        successIds = append(successIds, id)
    }

    // Mark published events as published
    if len(successIds) > 0 {
        _, _ = op.db.Exec(ctx, `
            UPDATE outbox SET published_at = NOW() WHERE id = ANY($1)
        `, successIds)
    }

    return nil
}

func (op *OutboxPublisher) Start(ctx context.Context) {
    ticker := time.NewTicker(5 * time.Second)
    defer ticker.Stop()

    for {
        select {
        case <-ticker.C:
            if err := op.PollAndPublish(ctx); err != nil {
                log.Printf("Error polling outbox: %v", err)
            }
        case <-ctx.Done():
            log.Println("OutboxPublisher stopped")
            return
        }
    }
}
```

### Payment Service: Idempotent Consumer

```go
// payment-service/inbox_consumer.go
package payment

import (
    "context"
    "encoding/json"
    "log"
    "time"

    "github.com/jackc/pgx/v5"
    "github.com/segmentio/kafka-go"
)

type PaymentService struct {
    db *pgx.Conn
}

type InboxMessage struct {
    EventId   string
    EventType string
    Payload   []byte
}

func (ps *PaymentService) ProcessEvent(ctx context.Context, msg *InboxMessage) error {
    // Step 1: Check if already processed
    var existingStatus string
    err := ps.db.QueryRow(ctx, `
        SELECT status FROM inbox WHERE event_id = $1
    `, msg.EventId).Scan(&existingStatus)

    if err == nil && existingStatus == "processed" {
        log.Printf("Event %s already processed, skipping", msg.EventId)
        return nil  // Idempotent
    }

    // Step 2: Process based on event type
    if msg.EventType == "ReservationCreated" {
        var event ReservationCreatedEvent
        json.Unmarshal(msg.Payload, &event)

        // Start transaction
        tx, _ := ps.db.Begin(ctx)
        defer tx.Rollback(ctx)

        // Insert into inbox (or skip if already exists)
        _, _ = tx.Exec(ctx, `
            INSERT INTO inbox (event_id, event_type, payload, status)
            VALUES ($1, $2, $3, 'pending')
            ON CONFLICT (event_id) DO NOTHING
        `, msg.EventId, msg.EventType, msg.Payload)

        // Process payment
        transactionId, err := ps.chargeCard(ctx, event.UserId, 15.99)
        if err != nil {
            return err
        }

        // Write transaction and mark inbox as processed (SAME TRANSACTION)
        _, _ = tx.Exec(ctx, `
            INSERT INTO transactions (id, booking_id, user_id, amount, status, created_at)
            VALUES ($1, $2, $3, $4, 'completed', NOW())
        `, transactionId, event.BookingId, event.UserId, 15.99)

        _, _ = tx.Exec(ctx, `
            UPDATE inbox SET status = 'processed', processed_at = NOW() WHERE event_id = $1
        `, msg.EventId)

        if err := tx.Commit(ctx); err != nil {
            return err
        }

        log.Printf("Payment processed for booking %s (transaction %s)", event.BookingId, transactionId)
    }

    return nil
}

func (ps *PaymentService) chargeCard(ctx context.Context, userId string, amount float64) (string, error) {
    // Call payment gateway (Stripe, Square, etc.)
    // Return transaction ID
    return "txn-" + uuid.NewString(), nil
}

// Kafka consumer loop
func (ps *PaymentService) ConsumeEvents(ctx context.Context, brokers []string, topic string) {
    reader := kafka.NewReader(kafka.ReaderConfig{
        Brokers: brokers,
        Topic: topic,
        GroupID: "payment-service",
        CommitInterval: time.Second,
    })
    defer reader.Close()

    for {
        msg, err := reader.ReadMessage(ctx)
        if err != nil {
            log.Printf("Error reading message: %v", err)
            continue
        }

        // Extract event_id from Kafka message (set as message Key)
        eventId := string(msg.Key)

        inboxMsg := &InboxMessage{
            EventId: eventId,
            EventType: msg.Topic,
            Payload: msg.Value,
        }

        if err := ps.ProcessEvent(ctx, inboxMsg); err != nil {
            log.Printf("Error processing event %s: %v", eventId, err)
            // In production: publish to DLQ, alert, etc.
            continue
        }
    }
}
```

### Database Schemas

```sql
-- Booking Service
CREATE TABLE outbox (
    id BIGSERIAL PRIMARY KEY,
    aggregate_id UUID NOT NULL,
    event_type VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL,
    partition_key VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    published_at TIMESTAMP NULL
);
CREATE INDEX idx_outbox_published ON outbox(published_at, created_at);

-- Payment Service
CREATE TABLE inbox (
    id BIGSERIAL PRIMARY KEY,
    event_id VARCHAR(255) UNIQUE NOT NULL,
    event_type VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    processed_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_inbox_status ON inbox(status, created_at);

CREATE TABLE transactions (
    id VARCHAR(255) PRIMARY KEY,
    booking_id UUID NOT NULL,
    user_id UUID NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    status VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
```

## Trade-offs & What Breaks

### What Breaks

**1. Outbox Table Growing Unbounded**
```
100,000 events/day × 365 days = 36M rows
With payload, this is 30GB of data
```
Fix: Archive old events (published_at < 90 days ago) to cold storage, then delete.

**2. Polling Overhead**
```
Polling every 1 second on a quiet system
99% of queries return 0 rows
Unnecessary database load
```
Fix: Use adaptive polling (slower when queue is empty) or CDC.

**3. Clock Skew**
```
Your server's clock is 10 seconds behind
Outbox event published_at = server_time
But the timestamp in Kafka might be different
Consumers might get events with future timestamps
```
Fix: Use database timestamps, not application timestamps. Use `NOW()` in SQL.

**4. Consumer Rebalancing with Kafka**
```
PaymentService has 3 consumer instances
They rebalance (one instance goes down)
Messages might be processed by different instances
Inbox pattern + idempotency key handles this, but latency increases
```
Fix: Kafka Streams or use a sticky assignment policy.

**5. Event Ordering with Multiple Aggregates**
```
Reservation created for booking_A
Payment processed for booking_B
Reservation created for booking_C
Events processed out of order at consumer (not a problem for different aggregates, but confusing in logs)
```
Fix: Use partition keys per aggregate. It's fine for events from different aggregates to be out of order.

## Interview Corner

**Q1: Explain the dual-write problem and the outbox pattern.**

A: Dual-write: Writing to database and message queue separately causes inconsistency if one fails. Outbox pattern: Write business data and event to the same database transaction. A background poller publishes events from the outbox table to the message queue. This ensures atomicity at the database level and eventual consistency at the messaging level.

**Q2: How does the outbox pattern guarantee at-least-once delivery?**

A: Business data + event are written atomically to the database. If the outbox poller crashes after publishing but before updating the `published_at` column, the event is republished on restart. This guarantees each event reaches the message queue at least once. Idempotent consumers (inbox pattern) deduplicate at the receiving end.

**Q3: What's the difference between the outbox pattern and CDC?**

A: **Outbox**: Explicit event writing to an outbox table, polled periodically. Simple to implement, ~5-10s latency, moderate database load.

**CDC**: Captures changes from the database transaction log (WAL). Sub-second latency, lower database load, but higher operational complexity.

Use CDC for high-volume, low-latency systems. Use outbox for simpler systems.

**Q4: How does the inbox pattern ensure idempotent processing?**

A: Consumer receives an event with an event_id. Before processing, check the inbox table for that event_id. If already processed, return immediately (idempotent). If not, process the business logic and insert/update the inbox in the same transaction. Ensures the event is processed exactly once despite retries or duplicates.

**Q5: Design the outbox + inbox for a WhatsApp-like system where a user sends a message.**

A: **Outbox (MessageService)**:
1. User sends message
2. Insert into messages table + insert into outbox (MessageSent event) in same transaction
3. Outbox poller publishes to Kafka

**Kafka topics**: user.{recipient_id}.messages (partition by recipient for ordering)

**Inbox (NotificationService)**:
1. Consume from Kafka
2. Check inbox for event_id (idempotent)
3. Insert notification, mark inbox as processed (same transaction)
4. Push notification to client

**Q6: How many rows can an outbox table safely hold before it becomes a problem?**

A: Depends on your database. PostgreSQL can handle 100M rows efficiently. But for query performance, you want to keep it under 50M active rows. Archive events older than 30-90 days to cold storage.

## Exercise

**Build a complete outbox + inbox system:**

1. Create PostgreSQL tables for outbox and inbox
2. Implement BookingService that writes to outbox
3. Implement OutboxPublisher that polls and publishes to Kafka (mock or real)
4. Implement PaymentService with inbox consumer
5. Verify: Create 100 bookings, ensure PaymentService processes all exactly once
6. Simulate Kafka failure: Stop Kafka, verify events queue in outbox, resume Kafka, verify publisher catches up
7. Simulate duplicate delivery: Publish same event twice, verify inbox deduplicates

Bonus:
- Implement archive/cleanup for old outbox rows
- Add metrics: publish latency, inbox processing latency
- Implement DLQ (dead-letter queue) for failed events

## Advanced Outbox Patterns

### Partitioning Outbox for Scale

**Problem**: Outbox table with 1 billion rows gets slow
```sql
SELECT * FROM outbox WHERE published_at IS NULL ORDER BY created_at LIMIT 100
```

**Solution: Table partitioning**
```sql
-- Partition by created_at (daily partitions)
CREATE TABLE outbox_2025_03_26 PARTITION OF outbox
    FOR VALUES FROM ('2025-03-26') TO ('2025-03-27');

-- Each partition is smaller, queries are faster
-- Old partitions can be archived to cold storage
```

**Publisher strategy:**
```go
// Poll only today's partition
rows, _ := db.Query(ctx, `
    SELECT * FROM outbox_2025_03_26
    WHERE published_at IS NULL
    LIMIT 100
`)
```

### Handling Clock Skew & Distributed Timestamps

**Problem**: Servers have different clocks
```
Server A: 10:00:00 → publishes event
Server B: 09:59:50 → has 10-second slower clock
Event timestamp: 09:59:50 (looks like it came from the past)
```

**Solution: Use database server time**
```go
// DON'T use time.Now() from application
// DO use the database server's NOW()

err := db.QueryRow(ctx, `
    INSERT INTO outbox (aggregate_id, event_type, payload, created_at)
    VALUES ($1, $2, $3, NOW())  -- Database provides timestamp
    RETURNING created_at
`, aggregateId, eventType, payload).Scan(&createdAt)
```

### Idempotency in Producer and Consumer

**Producer idempotency** (outbox pattern already ensures this):
```go
// Same business operation = same outbox events
// Even if called twice with same ID
db.Exec(`
    INSERT INTO outbox (aggregate_id, event_type, payload, idempotency_key)
    VALUES ($1, $2, $3, $4)
    ON CONFLICT (idempotency_key) DO NOTHING  -- Silently skip if already exists
`, aggregateId, eventType, payload, idempotencyKey)
```

**Consumer idempotency** (inbox pattern):
```go
// Same event_id = skip processing if already done
db.QueryRow(ctx, `
    SELECT status FROM inbox WHERE event_id = $1
`, eventId).Scan(&status)

if status == "processed" {
    return nil  // Already processed, idempotent
}
```

### Backpressure Handling

**Problem**: Events publish faster than consumer can process
```
Producer: 1000 events/sec
Consumer: 100 events/sec
Queue grows unbounded
```

**Solutions:**

1. **Pause Publishing**:
   ```go
   // If outbox is too large, pause accepting new writes
   var outboxSize int
   db.QueryRow(ctx, "SELECT COUNT(*) FROM outbox WHERE published_at IS NULL").Scan(&outboxSize)

   if outboxSize > 100000 {  // Threshold
       http.Error(w, "Service temporarily unavailable", http.StatusServiceUnavailable)
       return
   }
   ```

2. **Slow Down Polling**:
   ```go
   // If outbox is catching up, slow down new writes
   if outboxSize > 50000 {
       // Increase polling interval or reduce batch size
       ticker.Reset(10 * time.Second)  // Instead of 5
   }
   ```

3. **Separate Slow Consumers**:
   ```go
   // Send slow-to-process events to separate topic
   // ReportingService gets events from separate topic, slower SLA
   if isSlowEvent(eventType) {
       publishToTopic("events-reporting", event)
   } else {
       publishToTopic(eventType, event)  // Critical events, fast topic
   }
   ```

## Advanced Interview Questions

**Q7: You have 10 million events in the outbox, published_at is NULL. How do you recover?**

A: This is a backlog accumulation problem:
1. **Diagnose**: Why didn't events publish?
   - Publisher process crashed?
   - Kafka cluster unavailable?
   - Network partition?
   ```sql
   SELECT MAX(created_at) FROM outbox WHERE published_at IS NOT NULL;
   -- If this is 2 hours old, publisher has been stuck for 2 hours
   ```

2. **Drain the backlog**:
   ```go
   // Increase batch size temporarily
   batchSize := 1000  // Instead of 100

   // Run multiple publishers in parallel
   for i := 0; i < 10; i++ {
       go publisherWorker(i)  // 10 workers draining in parallel
   }
   ```

3. **Prevent future accumulation**:
   - Add alerts if outbox grows beyond threshold
   - Auto-scale publishers (more goroutines if outbox size > 10000)
   - Set max retention (drop very old unpublished events, alert SRE)

**Q8: Design outbox + inbox for a system with strict ordering requirements (e.g., transaction history).**

A: Outbox alone doesn't guarantee ordering across events (different partitions can reorder). For strict ordering:

1. **Partition key per user**:
   ```go
   // All events for user_id go to same Kafka partition
   db.Exec(`
       INSERT INTO outbox (..., partition_key)
       VALUES (..., $1)  // partition_key = user_id
   `, userId)
   ```

2. **Consumer: Process one at a time per user**:
   ```go
   // Kafka: Single consumer per partition (ensures ordering)
   // Inbox: Check sequence number
   var lastSeq int
   db.QueryRow(ctx, `
       SELECT MAX(sequence_num) FROM inbox WHERE user_id = $1
   `, userId).Scan(&lastSeq)

   if event.SequenceNum != lastSeq + 1 {
       // Out of order, requeue
       return errors.New("out of order")
   }
   ```

3. **Enable strict ordering**:
   ```sql
   CREATE TABLE inbox (
       id BIGSERIAL,
       event_id VARCHAR,
       user_id UUID,
       sequence_num INT,
       status VARCHAR,
       UNIQUE (user_id, sequence_num)  -- Enforce ordering
   );
   ```

**Q9: An inbox consumer processes event A, fails to update inbox status. On restart, processes A again. How do you prevent duplication downstream?**

A: Three layers of idempotency:

1. **Inbox deduplication**:
   ```sql
   -- Event A already in inbox with status=pending
   -- If crashed before UPDATE, retry will find it pending again
   UPDATE inbox SET status = 'processing' WHERE event_id = $1 AND status = 'pending'
   -- This is conditional: only update if pending
   ```

2. **Idempotency key in downstream system**:
   ```go
   // When processing event A (transaction creation), use event_id as idempotency key
   db.Exec(`
       INSERT INTO transactions (event_id, user_id, amount)
       VALUES ($1, $2, $3)
       ON CONFLICT (event_id) DO UPDATE SET amount = $3  -- Idempotent
   `, event.EventId, event.UserId, event.Amount)
   ```

3. **Version tracking**:
   ```go
   // Track which version of the event we processed
   var lastProcessedVersion int
   db.QueryRow(ctx, `
       SELECT MAX(version) FROM inbox_processed WHERE event_id = $1
   `, event.EventId).Scan(&lastProcessedVersion)

   if event.Version == lastProcessedVersion {
       return nil  // Already processed this version
   }
   ```

Result: Even if event A is processed 10 times, the downstream system creates only 1 transaction.


