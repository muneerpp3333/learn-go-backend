# The Saga Pattern: Distributed Transactions

## The Problem

You're in BookingService. A user wants to reserve a seat, process payment, and confirm the booking. Each step is in a different service:

1. **BookingService**: Reserve seat
2. **PaymentService**: Charge credit card
3. **NotificationService**: Send confirmation email

If all three services use the same database, you wrap in a transaction:
```sql
BEGIN;
  UPDATE seats SET reserved = true WHERE id = 'seat-123';
  INSERT INTO transactions ...;
  INSERT INTO emails ...;
COMMIT;
```

But they don't. Each service has its own database. **Traditional 2-phase commit (2PC) doesn't work at scale:**

```
1. Coordinator asks PaymentService: "Can you charge $15?"
   PaymentService locks funds, says "yes"
2. Coordinator asks NotificationService: "Can you send email?"
   NotificationService buffers email, says "yes"
3. Coordinator says "commit"
   Both execute
```

**Problems:**
- **Blocking**: PaymentService holds resources while waiting for NotificationService
- **Inconsistency**: If NotificationService fails, coordinator can't rollback the payment
- **Scalability**: Works for 2 services, fails for 6 services and long-running operations
- **Operational nightmare**: Hard to debug, hard to monitor, hard to recover from failures

At scale, you need a different approach: **Sagas**. A saga is a sequence of local transactions, each followed by a compensating transaction if failure occurs.

## Theory

### Choreography vs. Orchestration

#### Choreography-Based Saga

Services communicate via events. No central coordinator.

**Flow** (movie booking):
```
1. BookingService: User requests seat reservation
   → BookingService writes Reservation to DB
   → BookingService publishes "ReservationCreated" event

2. PaymentService: Subscribed to "ReservationCreated"
   → Processes payment
   → Publishes "PaymentProcessed" event

3. NotificationService: Subscribed to "PaymentProcessed"
   → Sends confirmation email
   → Publishes "EmailSent" event

If PaymentService fails:
4. PaymentService publishes "PaymentFailed" event

5. BookingService: Subscribed to "PaymentFailed"
   → Releases seat reservation
   → Publishes "ReservationCancelled" event
```

**Pros:**
- Loose coupling: Services don't call each other directly
- Scalable: Easy to add new steps (subscribing services)
- Simple to understand: Each service knows its job

**Cons:**
- Hard to debug: No central view of the entire workflow
- Cyclical dependencies: If BookingService subscribes to PaymentFailed, and PaymentService subscribes to ReservationCreated, circular logic can occur
- Testing is complex: Need to simulate multiple event flows
- No central visibility: Hard to track saga progress in production

#### Orchestration-Based Saga

A central coordinator tells each service what to do.

**Flow** (same booking example):
```
1. BookingServiceOrchestrator receives booking request
2. Calls BookingService: "Reserve seat"
   → Success or failure
3. If success, calls PaymentService: "Process payment"
   → Success or failure
4. If success, calls NotificationService: "Send email"
   → Success or failure
5. If any step fails, invoke compensation in reverse order
```

**Pros:**
- Central visibility: One place to see the entire workflow
- Easier testing: Mock the coordinator, test compensation flows
- Explicit: Clear order of operations
- Easier debugging: Logs follow the saga ID

**Cons:**
- Tight coupling: Orchestrator knows all services
- Single point of failure: If orchestrator crashes, saga hangs
- Requires saga persistence: Must survive restarts
- More complex code: Need to manage saga state machine

**When to use each:**
- **Choreography**: Few services (2-3), independent workflows, want loose coupling
- **Orchestration**: Many services (5+), complex workflows with many dependencies, need visibility

Most production systems use **orchestration** because visibility is critical at scale.

### Orchestration-Based Saga: Full Implementation

A saga has **steps**. Each step:
1. Executes a local transaction (ReserveT)
2. Publishes an event on success
3. Has a **compensating transaction** (ReserveT_Compensation) that undoes the step if a later step fails

**Example Saga: Movie Booking**

```
Step 1: ReserveSeat
   Action: BookingService reserves seat
   Compensation: Release seat reservation

Step 2: ProcessPayment
   Action: PaymentService charges credit card
   Compensation: Refund charge

Step 3: ConfirmBooking
   Action: BookingService marks booking as confirmed
   Compensation: Cancel booking (rollback)
```

**What happens if PaymentService fails:**
```
ReserveSeat (success)
ProcessPayment (FAILS)
→ Compensate PaymentService (skipped, nothing to refund)
→ Compensate ReserveSeat (release seat)
→ Saga aborted
```

**Saga State Machine:**
```
PENDING → [try ReserveSeat] → RESERVE_SEAT_PENDING
RESERVE_SEAT_PENDING → [success] → PROCESS_PAYMENT_PENDING
PROCESS_PAYMENT_PENDING → [success] → CONFIRM_BOOKING_PENDING
CONFIRM_BOOKING_PENDING → [success] → COMPLETED
CONFIRM_BOOKING_PENDING → [failure] → COMPENSATING
COMPENSATING → [compensate ConfirmBooking] → COMPENSATING
COMPENSATING → [compensate ProcessPayment] → COMPENSATING
COMPENSATING → [compensate ReserveSeat] → ABORTED
```

**Key: Idempotency**

Each step must be idempotent. Why? Steps might be retried.

```
ReserveSeat called twice with same request:
First call: Seat reserved, returns "success"
Second call (retry): Seat already reserved by same user, returns "success" (idempotent)
```

This requires using **idempotency keys**:
```go
// Idempotency key = unique ID for this action
// If ReserveSeat(idempotencyKey="idem-123") is called twice, both return same result

type ReserveRequest struct {
    IdempotencyKey string // Provided by caller
    SeatId string
    UserId string
}

type ReserveResult struct {
    Success bool
    SeatId string
}

func (s *SagaOrchestrator) ReserveSeat(req *ReserveRequest) (*ReserveResult, error) {
    // Check if this idempotency key was already processed
    if cached, ok := s.idempotencyCache[req.IdempotencyKey]; ok {
        return cached, nil
    }

    // Execute
    result := ...

    // Cache
    s.idempotencyCache[req.IdempotencyKey] = result
    return result, nil
}
```

### Compensating Transactions

A compensating transaction undoes the effect of a forward transaction.

**Forward Transaction**: `UPDATE seats SET reserved = true`
**Compensating Transaction**: `UPDATE seats SET reserved = false`

**Challenge: Partial Compensation**

What if compensation fails?

```
ReserveSeat: success
ProcessPayment: success
ConfirmBooking: success
Now compensate (saga was aborted by external error):
  Compensate ConfirmBooking: success
  Compensate ProcessPayment: **FAILS** (payment gateway unreachable)
  What now? Seat is unreserved but payment wasn't refunded
```

**Options:**
1. **Retry compensation**: Keep retrying until it succeeds (eventually consistent)
2. **Manual intervention**: Alert SRE to manually refund
3. **Parking lot**: Move saga to a "stuck" state for manual review
4. **Saga abort**: Some payment is non-refundable; accept the loss

Production systems often use a combination: retry with exponential backoff, then escalate to oncall.

### Saga Execution Coordinator (SEC) in Go

```go
package saga

import (
    "context"
    "database/sql"
    "fmt"
    "log"
    "time"
)

type SagaStep struct {
    Name    string
    Action  func(context.Context) error
    Compensate func(context.Context) error
}

type SagaStatus string

const (
    SagaPending      SagaStatus = "pending"
    SagaInProgress   SagaStatus = "in_progress"
    SagaCompleted    SagaStatus = "completed"
    SagaCompensating SagaStatus = "compensating"
    SagaAborted      SagaStatus = "aborted"
)

type SagaExecution struct {
    ID        string
    Steps     []SagaStep
    Status    SagaStatus
    History   []string // Log of steps executed
    db        *sql.DB
}

func NewSagaExecution(db *sql.DB, id string, steps []SagaStep) *SagaExecution {
    return &SagaExecution{
        ID:      id,
        Steps:   steps,
        Status:  SagaPending,
        History: []string{},
        db:      db,
    }
}

func (s *SagaExecution) Execute(ctx context.Context) error {
    s.Status = SagaInProgress
    s.logStep("saga_started")
    s.persist()

    var executedSteps []int

    for i, step := range s.Steps {
        s.logStep(fmt.Sprintf("step_%s_started", step.Name))

        err := step.Action(ctx)
        if err != nil {
            s.logStep(fmt.Sprintf("step_%s_failed: %v", step.Name, err))
            s.Status = SagaCompensating
            s.persist()

            // Compensate in reverse order
            s.compensate(ctx, executedSteps)
            s.Status = SagaAborted
            s.persist()
            return fmt.Errorf("saga aborted: step %s failed: %w", step.Name, err)
        }

        s.logStep(fmt.Sprintf("step_%s_completed", step.Name))
        executedSteps = append(executedSteps, i)
        s.persist()
    }

    s.Status = SagaCompleted
    s.logStep("saga_completed")
    s.persist()
    return nil
}

func (s *SagaExecution) compensate(ctx context.Context, executedSteps []int) {
    // Compensate in reverse order
    for i := len(executedSteps) - 1; i >= 0; i-- {
        stepIdx := executedSteps[i]
        step := s.Steps[stepIdx]

        s.logStep(fmt.Sprintf("step_%s_compensating", step.Name))

        // Retry compensation with exponential backoff
        maxRetries := 5
        for attempt := 0; attempt < maxRetries; attempt++ {
            err := step.Compensate(ctx)
            if err == nil {
                s.logStep(fmt.Sprintf("step_%s_compensated", step.Name))
                break
            }

            if attempt == maxRetries-1 {
                s.logStep(fmt.Sprintf("step_%s_compensation_failed_permanently: %v", step.Name, err))
                log.Printf("ALERT: Saga %s failed to compensate step %s. Manual intervention needed.", s.ID, step.Name)
                continue
            }

            backoff := time.Duration(1<<uint(attempt)) * time.Second
            time.Sleep(backoff)
        }
    }
}

func (s *SagaExecution) logStep(message string) {
    s.History = append(s.History, fmt.Sprintf("%s: %s", time.Now().Format(time.RFC3339), message))
}

func (s *SagaExecution) persist() error {
    // Save saga state to database
    query := `
        INSERT INTO saga_executions (id, status, history) VALUES ($1, $2, $3)
        ON CONFLICT (id) DO UPDATE SET status = $2, history = $3
    `
    _, err := s.db.Exec(query, s.ID, s.Status, s.History)
    return err
}
```

### Timeout Handling in Sagas

What if a step takes forever?

```
ProcessPayment called at 10:00:00
Waiting for payment gateway...
10:00:05 - still waiting
10:00:10 - still waiting
10:01:00 - timeout
→ Saga compensates
```

**The Problem**: The payment might have succeeded, but the response timed out. If you compensate by refunding, the user paid twice.

**The Solution**: Idempotent refunds + eventual consistency

```go
func ProcessPaymentWithTimeout(ctx context.Context, bookingId string, amount float64) (*PaymentResult, error) {
    // Create context with timeout
    ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
    defer cancel()

    // Call payment service
    result, err := paymentService.Charge(ctx, &ChargeRequest{
        BookingId: bookingId,
        Amount: amount,
        IdempotencyKey: bookingId, // Important: same booking ID = same charge
    })

    if err != nil && err == context.DeadlineExceeded {
        // Timeout. Payment *might* have succeeded.
        // Return a "pending" status
        return &PaymentResult{Status: "pending", BookingId: bookingId}, nil
    }

    return result, err
}

// In saga:
result, err := ProcessPaymentWithTimeout(...)
if result.Status == "pending" {
    // Don't compensate yet. Retry later.
    // Set up a background task to poll payment service for status
    s.schedulePoll(bookingId)
}
```

### State Machine Approach to Saga Orchestration

Instead of procedural code, define sagas as state machines.

```go
type SagaDefinition struct {
    Name  string
    States map[SagaState]StateHandler
}

type SagaState string
type StateHandler func(context.Context, *SagaExecution) (SagaState, error)

const (
    StateReserveSeat    SagaState = "reserve_seat"
    StateProcessPayment SagaState = "process_payment"
    StateConfirmBooking SagaState = "confirm_booking"
    StateCompleted      SagaState = "completed"
    StateAborted        SagaState = "aborted"
)

func NewMovieBookingSaga() *SagaDefinition {
    return &SagaDefinition{
        Name: "movie_booking",
        States: map[SagaState]StateHandler{
            StateReserveSeat: func(ctx context.Context, exec *SagaExecution) (SagaState, error) {
                err := exec.CallService("booking", "ReserveSeat", exec.Data["seat_id"])
                if err != nil {
                    return StateAborted, err
                }
                return StateProcessPayment, nil
            },
            StateProcessPayment: func(ctx context.Context, exec *SagaExecution) (SagaState, error) {
                err := exec.CallService("payment", "ProcessPayment", exec.Data["amount"])
                if err != nil {
                    return StateAborted, err
                }
                return StateConfirmBooking, nil
            },
            StateConfirmBooking: func(ctx context.Context, exec *SagaExecution) (SagaState, error) {
                err := exec.CallService("booking", "ConfirmBooking", exec.Data["booking_id"])
                if err != nil {
                    return StateAborted, err
                }
                return StateCompleted, nil
            },
            StateAborted: func(ctx context.Context, exec *SagaExecution) (SagaState, error) {
                // Compensate
                exec.CallService("booking", "ReleaseSeat", exec.Data["seat_id"])
                // Payment refund happens elsewhere or is retried
                return StateAborted, nil
            },
            StateCompleted: func(ctx context.Context, exec *SagaExecution) (SagaState, error) {
                return StateCompleted, nil
            },
        },
    }
}

func (exec *SagaExecution) Run(ctx context.Context, def *SagaDefinition) error {
    currentState := StateReserveSeat

    for {
        handler, ok := def.States[currentState]
        if !ok {
            return fmt.Errorf("unknown state: %s", currentState)
        }

        nextState, err := handler(ctx, exec)
        if err != nil && nextState == StateAborted {
            return err
        }

        currentState = nextState
        if nextState == StateCompleted || nextState == StateAborted {
            break
        }
    }

    return nil
}
```

### Saga and Eventual Consistency

**Key insight**: Sagas are eventually consistent. At some point during execution, the system is inconsistent:

```
After ReserveSeat: Seat is reserved, but payment hasn't processed yet
After ProcessPayment: Seat is reserved, payment is charged, but user hasn't been notified
After ConfirmBooking: Everything is consistent
```

**How to communicate this to users:**

1. **Optimistic UI**: Show booking as "Confirmed" immediately, even though payment is processing
2. **Pending States**: Show "Confirming your booking..." while saga executes
3. **Webhooks/SSE**: Notify user when saga completes or fails
4. **Polling**: User can query booking status endpoint

```go
// HTTP endpoint: POST /bookings (async)
func CreateBookingAsync(w http.ResponseWriter, r *http.Request) {
    var req BookingRequest
    json.NewDecoder(r.Body).Decode(&req)

    sagaId := uuid.NewString()

    // Start saga in background
    go sagaExecutor.Execute(sagaId, req)

    // Return immediately with saga ID
    w.WriteHeader(http.StatusAccepted) // 202
    json.NewEncoder(w).Encode(map[string]string{
        "saga_id": sagaId,
        "status_url": fmt.Sprintf("/bookings/saga/%s", sagaId),
    })
}

// HTTP endpoint: GET /bookings/saga/{id}
func GetSagaStatus(w http.ResponseWriter, r *http.Request) {
    sagaId := chi.URLParam(r, "id")
    exec := sagaExecutor.GetExecution(sagaId)

    json.NewEncoder(w).Encode(map[string]interface{}{
        "id": exec.ID,
        "status": exec.Status,
        "history": exec.History,
    })
}
```

Client code:
```javascript
// POST request returns 202 with saga_id
let sagaId = response.saga_id;

// Poll for status
async function pollSagaStatus() {
    while (true) {
        let resp = await fetch(`/bookings/saga/${sagaId}`);
        let data = await resp.json();

        if (data.status == "completed") {
            showConfirmation();
            break;
        } else if (data.status == "aborted") {
            showError();
            break;
        }

        await sleep(1000);
    }
}
```

## Production Code: Complete Movie Booking Saga

Full implementation with compensation.

```go
// saga/movie_booking_saga.go
package saga

import (
    "context"
    "database/sql"
    "fmt"
    "log"
    "time"

    "github.com/jackc/pgx/v5"
)

type MovieBookingSagaCoordinator struct {
    bookingDB *pgx.Conn
    paymentDB *pgx.Conn
}

type BookingSagaRequest struct {
    SagaId     string
    UserId     string
    ShowtimeId string
    SeatRow    int
    SeatCol    int
}

type BookingSagaResult struct {
    Success      bool
    BookingId    string
    ErrorMessage string
}

func (c *MovieBookingSagaCoordinator) ExecuteBookingSaga(ctx context.Context, req *BookingSagaRequest) *BookingSagaResult {
    log.Printf("[SAGA %s] Starting booking saga for user %s, showtime %s", req.SagaId, req.UserId, req.ShowtimeId)

    // Step 1: Reserve seat
    seatId, err := c.reserveSeat(ctx, req.SagaId, req.ShowtimeId, req.SeatRow, req.SeatCol, req.UserId)
    if err != nil {
        log.Printf("[SAGA %s] Failed to reserve seat: %v", req.SagaId, err)
        return &BookingSagaResult{Success: false, ErrorMessage: fmt.Sprintf("seat reservation failed: %v", err)}
    }
    log.Printf("[SAGA %s] Seat reserved: %s", req.SagaId, seatId)

    // Create booking record
    bookingId, err := c.createBookingRecord(ctx, req.SagaId, req.UserId, req.ShowtimeId, seatId)
    if err != nil {
        log.Printf("[SAGA %s] Failed to create booking record, compensating", req.SagaId)
        c.releaseSeat(context.Background(), req.SagaId, seatId)
        return &BookingSagaResult{Success: false, ErrorMessage: "booking creation failed"}
    }
    log.Printf("[SAGA %s] Booking created: %s", req.SagaId, bookingId)

    // Step 2: Process payment
    transactionId, err := c.processPayment(ctx, req.SagaId, bookingId, req.UserId, 15.99) // hardcoded price for demo
    if err != nil {
        log.Printf("[SAGA %s] Payment failed, compensating", req.SagaId)
        c.releaseSeat(context.Background(), req.SagaId, seatId)
        c.deleteBooking(context.Background(), req.SagaId, bookingId)
        return &BookingSagaResult{Success: false, ErrorMessage: fmt.Sprintf("payment failed: %v", err)}
    }
    log.Printf("[SAGA %s] Payment processed: %s", req.SagaId, transactionId)

    // Step 3: Confirm booking
    err = c.confirmBooking(ctx, req.SagaId, bookingId, transactionId)
    if err != nil {
        log.Printf("[SAGA %s] Failed to confirm booking, compensating", req.SagaId)
        c.refundPayment(context.Background(), req.SagaId, transactionId)
        c.releaseSeat(context.Background(), req.SagaId, seatId)
        c.deleteBooking(context.Background(), req.SagaId, bookingId)
        return &BookingSagaResult{Success: false, ErrorMessage: "confirmation failed"}
    }
    log.Printf("[SAGA %s] Booking confirmed successfully", req.SagaId)

    return &BookingSagaResult{
        Success:   true,
        BookingId: bookingId,
    }
}

// Step 1: Reserve Seat
func (c *MovieBookingSagaCoordinator) reserveSeat(ctx context.Context, sagaId, showtimeId string, row, col int, userId string) (string, error) {
    tx, _ := c.bookingDB.Begin(ctx)
    defer tx.Rollback(ctx)

    var seatId string
    err := tx.QueryRow(ctx, `
        UPDATE seats
        SET reserved_by = $1, reserved_at = NOW()
        WHERE showtime_id = $2 AND row = $3 AND col = $4 AND reserved_by IS NULL
        RETURNING id
    `, userId, showtimeId, row, col).Scan(&seatId)

    if err != nil {
        return "", err
    }

    // Log saga step
    tx.Exec(ctx, `
        INSERT INTO saga_steps (saga_id, step_name, status, data)
        VALUES ($1, 'reserve_seat', 'completed', jsonb_build_object('seat_id', $2))
    `, sagaId, seatId)

    tx.Commit(ctx)
    return seatId, nil
}

// Compensation: Release Seat
func (c *MovieBookingSagaCoordinator) releaseSeat(ctx context.Context, sagaId, seatId string) {
    _, err := c.bookingDB.Exec(ctx, `
        UPDATE seats
        SET reserved_by = NULL, reserved_at = NULL
        WHERE id = $1
    `, seatId)

    if err != nil {
        log.Printf("[SAGA %s] Failed to release seat %s: %v", sagaId, seatId, err)
        // Retry logic would go here
    }

    log.Printf("[SAGA %s] Seat released: %s", sagaId, seatId)
}

// Create booking record
func (c *MovieBookingSagaCoordinator) createBookingRecord(ctx context.Context, sagaId, userId, showtimeId, seatId string) (string, error) {
    tx, _ := c.bookingDB.Begin(ctx)
    defer tx.Rollback(ctx)

    var bookingId string
    err := tx.QueryRow(ctx, `
        INSERT INTO bookings (user_id, showtime_id, seat_id, status, created_at)
        VALUES ($1, $2, $3, 'pending', NOW())
        RETURNING id
    `, userId, showtimeId, seatId).Scan(&bookingId)

    if err != nil {
        return "", err
    }

    tx.Commit(ctx)
    return bookingId, nil
}

// Compensation: Delete booking
func (c *MovieBookingSagaCoordinator) deleteBooking(ctx context.Context, sagaId, bookingId string) {
    _, err := c.bookingDB.Exec(ctx, `
        DELETE FROM bookings WHERE id = $1
    `, bookingId)

    if err != nil {
        log.Printf("[SAGA %s] Failed to delete booking %s: %v", sagaId, bookingId, err)
    }

    log.Printf("[SAGA %s] Booking deleted: %s", sagaId, bookingId)
}

// Step 2: Process Payment
func (c *MovieBookingSagaCoordinator) processPayment(ctx context.Context, sagaId, bookingId, userId string, amount float64) (string, error) {
    ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
    defer cancel()

    tx, _ := c.paymentDB.Begin(ctx)
    defer tx.Rollback(ctx)

    var transactionId string
    err := tx.QueryRow(ctx, `
        INSERT INTO transactions (booking_id, user_id, amount, status, created_at, idempotency_key)
        VALUES ($1, $2, $3, 'pending', NOW(), $4)
        RETURNING id
    `, bookingId, userId, amount, fmt.Sprintf("booking-%s", bookingId)).Scan(&transactionId)

    if err != nil {
        return "", fmt.Errorf("failed to create transaction record: %w", err)
    }

    // In production, call external payment gateway here
    // For demo, just mark as completed
    _, err = tx.Exec(ctx, `
        UPDATE transactions SET status = 'completed' WHERE id = $1
    `, transactionId)

    tx.Commit(ctx)
    return transactionId, nil
}

// Compensation: Refund Payment
func (c *MovieBookingSagaCoordinator) refundPayment(ctx context.Context, sagaId, transactionId string) {
    // Retry logic for refunds
    maxRetries := 3
    for attempt := 0; attempt < maxRetries; attempt++ {
        tx, _ := c.paymentDB.Begin(context.Background())

        _, err := tx.Exec(context.Background(), `
            UPDATE transactions SET status = 'refunded' WHERE id = $1
        `, transactionId)

        if err == nil {
            tx.Commit(context.Background())
            log.Printf("[SAGA %s] Transaction refunded: %s", sagaId, transactionId)
            return
        }

        tx.Rollback(context.Background())

        if attempt < maxRetries-1 {
            backoff := time.Duration(1<<uint(attempt)) * time.Second
            time.Sleep(backoff)
        }
    }

    log.Printf("[SAGA %s] ALERT: Failed to refund transaction %s after %d retries. Manual intervention needed.", sagaId, transactionId, maxRetries)
}

// Step 3: Confirm Booking
func (c *MovieBookingSagaCoordinator) confirmBooking(ctx context.Context, sagaId, bookingId, transactionId string) error {
    tx, _ := c.bookingDB.Begin(ctx)
    defer tx.Rollback(ctx)

    _, err := tx.Exec(ctx, `
        UPDATE bookings
        SET status = 'confirmed', transaction_id = $1, confirmed_at = NOW()
        WHERE id = $2
    `, transactionId, bookingId)

    if err != nil {
        return err
    }

    tx.Commit(ctx)
    return nil
}
```

### Observability: Tracing a Saga

Every saga step should be logged with a correlation ID.

```go
type SagaLogger struct {
    db *pgx.Conn
}

func (sl *SagaLogger) LogStep(ctx context.Context, sagaId, stepName string, status string, data map[string]interface{}) {
    _, _ = sl.db.Exec(ctx, `
        INSERT INTO saga_step_log (saga_id, step_name, status, data, timestamp)
        VALUES ($1, $2, $3, $4, NOW())
    `, sagaId, stepName, status, data)
}

// Query saga progress
func QuerySagaProgress(ctx context.Context, db *pgx.Conn, sagaId string) ([]map[string]interface{}, error) {
    rows, _ := db.Query(ctx, `
        SELECT step_name, status, data, timestamp
        FROM saga_step_log
        WHERE saga_id = $1
        ORDER BY timestamp ASC
    `, sagaId)

    var steps []map[string]interface{}
    for rows.Next() {
        var stepName, status string
        var data []byte
        var ts time.Time
        rows.Scan(&stepName, &status, &data, &ts)
        steps = append(steps, map[string]interface{}{
            "step": stepName,
            "status": status,
            "data": string(data),
            "timestamp": ts,
        })
    }

    return steps, nil
}

// Dashboard query: SELECT saga_id, status, COUNT(*) FROM saga_executions GROUP BY saga_id, status
// Real-time: Show sagas in progress, aborted, completed
```

## Trade-offs & What Breaks

### What Breaks

**1. Partial Failures During Compensation**
```
ProcessPayment succeeded and charged $15
ConfirmBooking failed
→ Start compensation
Compensation: Refund fails (payment gateway unavailable)
→ Seat is released but user is charged
```
Fix: Retry with exponential backoff, escalate to SRE for manual refund.

**2. Out-of-Order Events**
```
PaymentProcessed event arrives before ReservationCreated event (network reordering)
PaymentService tries to apply payment, but reservation doesn't exist yet
```
Fix: Use event versioning and handle missing preconditions gracefully. Compensation is idempotent.

**3. Saga Participant Unavailable**
```
PaymentService crashes during step 2
Saga hangs waiting for payment response
→ No compensation, no completion
```
Fix: Timeout + retry. If all retries fail, move to "stuck" state and alert SRE.

**4. Distributed Monolith**
```
Three services, but they all have to succeed in sequence
It's just a distributed version of 2PC
Doesn't solve the problem
```
Fix: Make services truly independent. Use async communication where possible.

**5. Saga Coordinator Failure**
```
Orchestrator crashes after step 1 but before step 2
On restart, did step 2 execute? Unknown.
```
Fix: Persist saga state to database. On restart, replay from last step.

## Interview Corner

**Q1: Explain the saga pattern. When would you use it vs. 2PC?**

A: Saga is a sequence of local transactions with compensating transactions. Used for distributed transactions where 2PC fails:
- 2PC: All-or-nothing, blocking, doesn't scale
- Saga: Eventually consistent, non-blocking, scales to many services

Use saga when you have multiple services that each have their own database and you can tolerate eventual consistency.

**Q2: Choreography vs. orchestration sagas?**

A: **Choreography**: Services communicate via events. BookingService publishes "ReservationCreated", PaymentService subscribes. Loose coupling but harder to debug.

**Orchestration**: Central coordinator tells each service what to do. Easy to debug and test, but tighter coupling.

Use orchestration in production systems for visibility. Choreography for simple, independent workflows.

**Q3: How do you handle compensation failures?**

A: Retry with exponential backoff. If retries exhaust, move saga to a "stuck" state and alert on-call SRE. In extreme cases (regulatory requirements), accept the loss or escalate to manual intervention.

**Q4: Design a saga for airline booking: Reserve seat → Select meal → Purchase insurance. What happens if meal service fails?**

A:
- Reserve seat: success
- Select meal: FAILS
- Compensate: Release seat
- Result: Booking aborted

If you want to allow partial success (user gets seat but no meal), you'd need a different saga structure: mark meal as "optional" and continue if it fails.

**Q5: How do you test sagas?**

A:
1. Unit test each step (mock service calls)
2. Mock services to fail at different points
3. Verify compensation is called correctly
4. Verify idempotency (same step, same result)
5. Integration test with real databases

**Q6: What's the latency overhead of a saga?**

A: Depends on the number of steps and communication method. A 3-step saga with gRPC: ~50-100ms per step, so 150-300ms total. Add network latency, and you're looking at 300-500ms for a simple booking.

## Exercise

**Implement a saga for movie booking:**

1. Create three PostgreSQL tables: `bookings`, `transactions`, `saga_executions`
2. Implement the three saga steps (ReserveSeat, ProcessPayment, ConfirmBooking) as separate functions
3. Implement compensation for each step
4. Create a saga orchestrator that executes all three steps
5. Add a background goroutine that retries failed compensations
6. Add logging to track saga progress
7. Write a unit test that simulates PaymentService failing and verifies compensation

Bonus:
- Implement saga persistence (save state to DB after each step)
- Implement saga replay (resume interrupted sagas on restart)
- Add idempotency key support

## Advanced Saga Patterns

### Nested Sagas: Sagas Within Sagas

Complex business processes sometimes need hierarchical sagas.

**Example**: Movie release workflow
```
1. CreateMovieSaga
   1.1 CreateMovieMetadataSaga (internal saga)
       - Create movie record
       - Create movie images
       - Create movie translations
   1.2 CreateDistributionSaga (external saga)
       - Contact distributor
       - Get distribution agreement
       - Set pricing
   1.3 PublishMovieSaga
       - Add to catalog
       - Publish to partners
```

**Implementation:**
```go
func (exec *SagaExecutor) ExecuteCreateMovieSaga(ctx context.Context, req *MovieRequest) error {
    // Step 1: Internal saga
    if err := exec.ExecuteCreateMovieMetadataSaga(ctx, req); err != nil {
        // Compensate: Delete movie metadata
        return err
    }

    // Step 2: External saga
    if err := exec.ExecuteCreateDistributionSaga(ctx, req); err != nil {
        // Compensate: Delete distribution data, but movie metadata stays
        // This is a **saga anti-pattern**: inconsistent state
        return err
    }

    return nil
}
```

**Anti-pattern**: Mixing nested sagas with different compensation strategies. If an inner saga compensation fails, the outer saga doesn't know about it.

**Better approach**: Use choreography at top level, orchestration at each level. Or keep sagas flat and simple.

### Saga Recovery Strategies

**Problem**: A saga is partially executed, then the coordinator crashes.
```
Step 1: ReserveSeat (completed)
Step 2: ProcessPayment (started but no response)
Coordinator crashes
On restart: Is the payment processing? Did it fail? Unknown state.
```

**Recovery strategies:**

1. **Retry from last known state**
   ```go
   // Read last state from database
   lastState := GetLastSagaState(sagaId)

   // Resume from that point
   if lastState == "payment_processing" {
       // Check payment service: has payment completed?
       status := paymentService.GetPaymentStatus(bookingId)
       if status == "completed" {
           // Already done, skip to next step
           continueFromNextStep()
       } else if status == "pending" {
           // Retry payment
           retryPayment()
       } else {
           // Unknown state, escalate to SRE
           EscalateToSRE(sagaId)
       }
   }
   ```

2. **Idempotent compensation**
   ```go
   // Compensation should succeed even if called multiple times
   func CompensatePayment(ctx context.Context, bookingId string) error {
       // Check if already refunded
       if isAlreadyRefunded(bookingId) {
           return nil  // Idempotent: already done
       }

       // Otherwise, refund
       return refund(bookingId)
   }
   ```

3. **Dead Letter Queue (DLQ)**
   ```go
   // If saga cannot be recovered, send to DLQ for manual review
   if !CanRecover(saga) {
       dlq.Send(saga)
       AlertSRE("Unrecoverable saga", sagaId)
   }
   ```

### Saga Monitoring & Observability

**Metrics:**
```go
type SagaMetrics struct {
    TotalStarted    prometheus.Counter  // Total sagas started
    TotalCompleted  prometheus.Counter  // Total sagas completed successfully
    TotalAborted    prometheus.Counter  // Total sagas aborted
    DurationSeconds prometheus.Histogram // Saga execution time
    StepLatency     prometheus.Histogram // Per-step latency
}

// Track every saga
sagaMetrics.TotalStarted.Inc()

// Track each step
start := time.Now()
err := step.Execute(ctx)
sagaMetrics.StepLatency.Observe(time.Since(start).Seconds())

// Track final result
if saga.Status == "completed" {
    sagaMetrics.TotalCompleted.Inc()
} else if saga.Status == "aborted" {
    sagaMetrics.TotalAborted.Inc()
}
```

**Tracing:**
```go
// Every saga gets a unique correlation ID
sagaId := uuid.NewString()
ctx = context.WithValue(ctx, "saga_id", sagaId)

// Every RPC includes correlation ID
log.Printf("[saga_id=%s] Step 1: ReserveSeat", sagaId)
paymentService.Charge(ctx, &ChargeRequest{
    BookingId: bookingId,
    // gRPC interceptor extracts saga_id from context and sends in metadata
})
log.Printf("[saga_id=%s] Step 2: PaymentProcessed", sagaId)
```

**Dashboard Query:**
```sql
-- Show sagas in progress, avg duration, abort rate
SELECT
  status,
  COUNT(*) as count,
  ROUND(AVG(EXTRACT(EPOCH FROM (ended_at - started_at))), 2) as avg_duration_seconds,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 2) as percent
FROM saga_executions
WHERE started_at > NOW() - INTERVAL 24 HOURS
GROUP BY status;

-- Result:
-- completed | 9850 | 1.23 | 98.5%
-- aborted   | 150  | 0.95 | 1.5%
```

## Advanced Interview Questions

**Q7: You're running a 100-step saga that takes 30 minutes. A step times out midway through. How do you handle it?**

A: Multi-faceted approach:
1. **Timeout handling**: Set per-step timeout (e.g., 5 min). If exceeded, mark as "timeout" (not failure)
2. **Retry logic**: Wait 30 seconds, retry the step (might have been transient)
3. **Compensation decision**: After retries, decide: compensate or escalate
4. **Escalation**: If unsure about state, ask the service directly
   ```go
   // Is the payment actually complete?
   status, _ := paymentService.GetPaymentStatus(transactionId)
   if status == "completed" {
       // Good, continue to next step
   } else if status == "failed" {
       // Compensate
   } else if status == "unknown" {
       // Escalate to SRE
   }
   ```
5. **Manual intervention queue**: For unsolved sagas, alert SRE with all context

**Q8: Design a saga for a food delivery app (restaurant → kitchen → delivery).**

A:
```
CreateOrderSaga:
1. ReserveFood (Kitchen Service)
   Compensation: Cancel food prep
2. EstimateDelivery (Delivery Service)
   Compensation: Free up delivery slot
3. ChargePayment (Payment Service)
   Compensation: Refund
4. NotifyRestaurant (Notification Service)
   (No compensation: non-critical)
5. ConfirmOrder (Order Service)
   Compensation: Cancel order

If step 2 fails (no delivery available):
  Compensation: Cancel food prep, nothing charged yet
  Return: "Delivery not available, try again"

If step 3 fails (payment declined):
  Compensation: Release delivery slot, cancel food prep
  Return: "Payment declined, please retry"
```

**Q9: A saga's compensation fails 5 times. What's your escalation path?**

A:
1. **Log the error**: Include saga state, step name, error message
2. **Alert**: Send alert to on-call SRE with saga link
3. **Manual review**: SRE checks saga state in database
4. **Manual intervention options**:
   - Retry compensation manually
   - Mark saga as "accepted loss" (we can't refund, close the loop)
   - Refund manually via payment system
5. **Post-mortem**: Why did compensation fail? (service down, resource exhausted, bug)
6. **Automation**: Implement fix (retry with different strategy, handle edge case)


