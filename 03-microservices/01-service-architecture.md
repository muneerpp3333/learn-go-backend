# Service Architecture & Decomposition

## The Problem

You've built a monolithic booking system that works. It's a single Go binary handling users, catalogs, bookings, and payments. As TPS (transactions per second) increases and teams grow, you hit walls:

- **Deployment fear**: One team's small change requires testing the entire codebase
- **Resource contention**: The payment processor is single-threaded, blocking high-traffic seat search
- **Technology lock-in**: The entire system must scale with your slowest component
- **Team friction**: 15 engineers stepping on each other's toes in one codebase

Monoliths aren't evil—they're just wrong at scale. The question is: **when and how do you decompose?**

## Theory

### The Strangler Fig Pattern: Incremental Migration

Don't rewrite. Instead, grow microservices beside the monolith like a strangler fig tree that eventually replaces its host.

**Phase 1: Identify a Subdomain to Extract**
- Choose low-risk, loosely coupled services first (often payment, notifications, search)
- Extract UserService? No—it's heavily referenced everywhere
- Extract PaymentService? Yes—external dependency, infrequent changes, distinct failure domain

**Phase 2: Create a Reverse Proxy / API Gateway**
- All traffic flows through the gateway
- Gateway routes `POST /payments/*` to new PaymentService
- Everything else routes to monolith
- Teams deploy independently

**Phase 3: Gradually Migrate Data**
- New PaymentService gets its own database
- Both systems are source-of-truth temporarily (dual-write with retry logic)
- Monolith gradually stops writing to payment tables
- Eventually, monolith reads from PaymentService (becomes a client)

**Phase 4: The Cutover**
- When monolith stops writing payments, remove dual-write logic
- Gateway now 100% routes payments to new service
- Deprecate and remove old payment code from monolith

**The key**: At no point is the system completely broken. Teams keep shipping features in the monolith while the migration proceeds in parallel.

### Domain-Driven Design (DDD): Finding Service Boundaries

Microservice boundaries should align with **business domains**, not technical layers. This is DDD.

**Core Concepts:**

1. **Bounded Contexts**: A bounded context is an explicit boundary within which a domain model is defined and applicable. Example:
   - **Booking Context**: Understands "Reservation," "Seat," "Price," "Confirmation"
   - **Payment Context**: Understands "Transaction," "Refund," "Authorization"
   - **Catalog Context**: Understands "Movie," "Showtime," "Theater"
   - These contexts have completely different meanings of "Reservation" (Booking sees it as a held seat; Payment doesn't care)

2. **Ubiquitous Language**: The Booking team and Payment team speak the same language *within their context* but may use different terms across contexts. "Confirmation" in Booking becomes "Receipt" in Payment. This is expected.

3. **Aggregates**: A cluster of entities treated as a single unit. Example:
   - Booking Aggregate: (Reservation, Seat[], Customer) = one consistency boundary
   - Payment Aggregate: (Transaction, Receipt, Refund[]) = one consistency boundary
   - Each aggregate has a root entity (Reservation, Transaction) with an ID
   - When you change a Reservation, you change it atomically within a transaction
   - You never change a Payment as a side effect of changing a Reservation

4. **Domain Events**: When something important happens in one domain, it publishes an event:
   - ReservationCreated (Booking domain)
   - PaymentProcessed (Payment domain)
   - These events are how domains communicate asynchronously

**Why this matters for microservices**: If you split a service along aggregate boundaries, you minimize cross-service transactions. Each service owns its aggregates. If you split incorrectly (putting half a Booking aggregate in Booking Service and the other half in InventoryService), you'll have cascading failures.

### Service Decomposition Strategies

**1. By Business Capability**
Organize around what the business does:
- **UserService**: Authentication, profiles, preferences
- **CatalogService**: Movies, showtimes, theaters
- **BookingService**: Reservations, seat holds
- **PaymentService**: Transactions, refunds
- **NotificationService**: Emails, SMS

Each service owns its data model and database. The teams that own customer data, payment data, etc., can deploy independently.

**2. By Subdomain**
DDD distinguishes:
- **Core Subdomains**: Unique to your business (Booking logic)
- **Supporting Subdomains**: Important but not unique (User management, you could buy this as SaaS)
- **Generic Subdomains**: Commodity (payment processing, already solved)

Invest heavily in core subdomains. Offload generic subdomains to CQRS or SaaS. Supporting subdomains get basic treatment.

**3. By Team Ownership**
- **Two-Pizza Rule**: If a service requires more than one two-pizza team, it's too big
- **Conway's Law**: Microservice boundaries will mirror your org structure anyway, so architect accordingly
- Example: If you have one strong Payment team, they own PaymentService. One team owns BookingService.

### Communication Patterns: Sync vs. Async

#### Synchronous Communication (REST, gRPC)

**REST API Example**:
```go
// UserService exposes:
GET /users/{id}
POST /users

// BookingService calls UserService synchronously:
resp, err := http.Get("http://user-service/users/123")
```

**Pros**:
- Simple to understand and debug
- Immediate feedback
- Easy to test locally

**Cons**:
- Tight coupling: If UserService is down, BookingService can't book
- Cascading failures: One slow service slows everything down
- Scaling challenges: Deep call stacks (BookingService → UserService → NotificationService)

#### Asynchronous Communication (Events, Messages)

**Event-Driven Example**:
```
BookingService creates a Reservation
  → Publishes "ReservationCreated" event to message queue
UserService subscribes to "ReservationCreated"
  → Processes asynchronously, might fail and retry
NotificationService subscribes to "ReservationCreated"
  → Sends confirmation email asynchronously
```

**Pros**:
- Loose coupling: Services don't call each other directly
- Resilience: If NotificationService is down, booking still succeeds
- Scalability: Services scale independently

**Cons**:
- Complexity: Requires message queues, eventual consistency
- Debugging: Distributed tracing becomes essential
- Operational overhead: Need replay mechanisms for failed events

**When to use each:**
- **Sync (gRPC/REST)**: When you need an immediate response (user profile lookup, seat availability check)
- **Async (Events)**: When you can tolerate latency (sending confirmation emails, updating analytics)
- **Hybrid**: Booking creation is synchronous (immediate seat hold), but confirmation email is async

### gRPC Deep Dive for Microservices

**Why gRPC over REST?**
- Binary protocol (faster than JSON)
- HTTP/2 (multiplexing, server push)
- Streaming (native support for server, client, bidirectional)
- Protobuf schema (self-documenting, language-agnostic)
- Lower latency (critical for internal microservice calls)

**Protobuf Definition** (`booking.proto`):
```protobuf
syntax = "proto3";
package booking.v1;

service BookingService {
  rpc ReserveSeat(ReserveSeatRequest) returns (ReserveSeatResponse);
  rpc GetAvailableSeats(GetAvailableSeatsRequest) returns (stream Seat);
  rpc StreamReservations(stream ReservationRequest) returns (stream ReservationResponse);
}

message ReserveSeatRequest {
  string showtime_id = 1;
  int32 seat_row = 2;
  int32 seat_col = 3;
  string user_id = 4;
}

message ReserveSeatResponse {
  bool success = 1;
  string reservation_id = 2;
  string error_message = 3;
}

message Seat {
  int32 row = 1;
  int32 col = 2;
  bool available = 3;
}
```

**Unary RPC** (one request, one response):
```go
conn, _ := grpc.Dial("booking-service:50051")
client := booking.NewBookingServiceClient(conn)
resp, _ := client.ReserveSeat(ctx, &booking.ReserveSeatRequest{
    ShowtimeId: "show-123",
    SeatRow: 5,
    SeatCol: 10,
    UserId: "user-456",
})
fmt.Println(resp.ReservationId)
```

**Server Streaming** (one request, multiple responses):
```go
// Server sends multiple seats one by one
stream, _ := client.GetAvailableSeats(ctx, &booking.GetAvailableSeatsRequest{
    ShowtimeId: "show-123",
})
for {
    seat, err := stream.Recv()
    if err == io.EOF { break }
    fmt.Printf("Seat available: %d-%d\n", seat.Row, seat.Col)
}
```

**Client Streaming** (multiple requests, one response):
```go
// Client sends multiple reservation requests
stream, _ := client.StreamReservations(ctx)
for i := 0; i < 100; i++ {
    stream.Send(&booking.ReservationRequest{...})
}
resp, _ := stream.CloseAndRecv()
fmt.Println(resp.ConfirmedCount)
```

**Bidirectional Streaming**: Both sides send and receive messages concurrently. Useful for long-lived connections like real-time seat availability updates.

**gRPC Interceptors** (middleware):
```go
// Unary interceptor (for unary RPCs)
func LoggingInterceptor(ctx context.Context, req interface{}, info *grpc.UnaryServerInfo,
    handler grpc.UnaryHandler) (interface{}, error) {
    log.Printf("RPC: %s", info.FullMethod)
    return handler(ctx, req)
}

// Register with server
grpc.NewServer(grpc.UnaryInterceptor(LoggingInterceptor))
```

**Load Balancing**: gRPC supports client-side load balancing using the `resolver` interface. Modern deployments use Kubernetes services or dedicated load balancers (e.g., nginx-ingress with gRPC support).

### REST API Design for Microservices

While gRPC is great for internal communication, external APIs and legacy integrations still use REST.

**Versioning Strategies:**

1. **URL Versioning** (explicit, easy to deprecate):
   ```
   GET /v1/bookings/{id}
   GET /v2/bookings/{id}  // New schema
   ```

2. **Header Versioning** (cleaner URLs, hidden versioning):
   ```
   GET /bookings/{id}
   Header: Accept: application/vnd.booking.v2+json
   ```

**HATEOAS** (Hypermedia As The Engine Of Application State):
Instead of just returning data, include links to related resources:
```json
{
  "id": "booking-123",
  "status": "confirmed",
  "showtime": "show-456",
  "_links": {
    "self": { "href": "/bookings/booking-123" },
    "cancel": { "href": "/bookings/booking-123/cancel", "method": "POST" },
    "showtime": { "href": "/showtimes/show-456" }
  }
}
```

This lets clients discover actions without hard-coding URLs. Less common in APIs but very useful for complex workflows.

**Pagination for Large Datasets:**
```json
{
  "data": [...],
  "pagination": {
    "page": 2,
    "limit": 50,
    "total": 500,
    "next": "/bookings?page=3&limit=50",
    "prev": "/bookings?page=1&limit=50"
  }
}
```

**Idempotency Keys** (critical for retries):
```
POST /bookings
Header: Idempotency-Key: uuid-123-456
Body: { "showtime_id": "show-123", ... }
```

Server stores the Idempotency-Key and response. If the request is retried with the same key, return the cached response instead of creating a duplicate booking.

```go
func CreateBooking(w http.ResponseWriter, r *http.Request) {
    idempotencyKey := r.Header.Get("Idempotency-Key")

    // Check cache
    if cached, ok := idempotencyCache[idempotencyKey]; ok {
        json.NewEncoder(w).Encode(cached)
        return
    }

    // Process booking
    booking := ...

    // Cache response
    idempotencyCache[idempotencyKey] = booking
    json.NewEncoder(w).Encode(booking)
}
```

### Service Mesh: Sidecar Proxies & Mutual TLS

A **Service Mesh** (Istio, Linkerd) adds a proxy sidecar to every service pod. These proxies intercept all network traffic and provide:

1. **Mutual TLS (mTLS)**: Automatic encryption and authentication between services
   - No need to manage certificates in application code
   - Mesh handles rotation
   - Automatic service-to-service authentication

2. **Traffic Management**: Circuit breakers, retries, timeouts at the mesh level
   - Don't implement retries in every service
   - Mesh handles it consistently
   - Easier to tune globally

3. **Observability**: Automatic tracing and metrics
   - Every RPC is traced automatically
   - No instrumentation code needed in services

**Trade-off**: Service meshes add ~10-15% latency overhead and significant operational complexity. Only adopt when you have 10+ services and need sophisticated traffic management.

### Database-per-Service: Why It's Mandatory

**The Anti-Pattern: Shared Database**
```
UserService, BookingService, PaymentService all access shared PostgreSQL
```
**Problems:**
- Tight coupling at the data layer
- Can't scale UserService independently (schema changes block BookingService)
- One service's bad query kills everyone
- Distributed transactions become necessary (expensive, often inconsistent)

**The Right Way: Database-per-Service**
```
UserService → PostgreSQL (user_db)
BookingService → PostgreSQL (booking_db)
PaymentService → PostgreSQL (payment_db)
```

**But how do you query across services?**

1. **Synchronous Call**: BookingService calls UserService API
   ```go
   user, err := userServiceClient.GetUser(ctx, userId)
   ```
   Cons: Latency, cascading failures

2. **Event-Driven Denormalization**:
   - UserService publishes "UserCreated" events
   - BookingService subscribes and maintains a denormalized copy of user data
   - BookingService's copy is eventually consistent but fast for reads
   ```go
   // BookingService database schema
   CREATE TABLE denormalized_users (
       id UUID PRIMARY KEY,
       name VARCHAR,
       email VARCHAR,
       updated_at TIMESTAMP
   );
   ```

3. **Search Indices**: Use Elasticsearch or similar for cross-service queries
   - Elasticsearch has data from all services
   - Used for analytics, search, not operational queries

### Event-Driven Architecture

**Domain Events vs. Integration Events:**

- **Domain Event**: Something significant happened *within* a service
  - ReservationCreated (in Booking service's database)
  - Used for coordinating within the bounded context
  - Example: When a Reservation is created, trigger a "send confirmation email" event within the same service

- **Integration Event**: A domain event published for other services to consume
  - ReservationCreated (published to Kafka/NATS topic)
  - Other services subscribe and take action
  - Example: PaymentService subscribes to ReservationCreated and pre-authorizes payment

**Event Sourcing** (when you care about history):
Instead of storing just the current state:
```
Reservation: { id: "res-123", status: "confirmed", seat: "5-10" }
```

Store the entire history:
```
ReservationCreated: { reservation_id: "res-123", user_id: "user-456", showtime: "show-789" }
SeatAssigned: { reservation_id: "res-123", seat: "5-10" }
PaymentProcessed: { reservation_id: "res-123", amount: 15.99 }
ReservationConfirmed: { reservation_id: "res-123" }
```

**Pros:**
- Complete audit trail
- Can rebuild state at any point in time
- Temporal queries ("what did the user's reservation look like on Jan 15?")

**Cons:**
- Added complexity (need to project events to current state)
- Storage overhead
- Eventual consistency challenges

Most services don't need event sourcing. Use it only for highly regulatory domains (finance, healthcare) or when you need the audit trail.

## Production Code: Movie Booking Service Decomposition

A complete decomposition from monolith to 4 microservices.

### Monolithic Starting Point (Simplified)
```go
package main

import "database/sql"

type Booking struct {
    ID        string
    UserID    string
    ShowtimeID string
    SeatRow   int
    SeatCol   int
    Status    string
    CreatedAt time.Time
}

type Movie struct {
    ID    string
    Title string
}

type Showtime struct {
    ID      string
    MovieID string
    Time    time.Time
    Theater string
}

// One big handler for everything
func createBooking(w http.ResponseWriter, r *http.Request) {
    // 1. Fetch user from users table
    // 2. Fetch showtime from showtimes table
    // 3. Check seat availability in bookings table
    // 4. Create booking
    // 5. Process payment (sync call to payment API, stored in db)
    // 6. Send confirmation email
    // All in one transaction (or multiple if email fails)
}

// When traffic grows:
// - Seat lookup is slow because bookings table is huge
// - Scaling the entire service to fix seat lookup
// - Payment processing blocking booking creation
```

### Decomposed Architecture

**User Service** (handles users, auth):
```go
// user-service/main.go
package main

import (
    "github.com/jackc/pgx/v5"
    "google.golang.org/grpc"
)

type UserServer struct {
    db *pgx.Conn
}

func (s *UserServer) GetUser(ctx context.Context, req *pb.GetUserRequest) (*pb.User, error) {
    var user pb.User
    err := s.db.QueryRow(ctx, "SELECT id, email, name FROM users WHERE id = $1", req.Id).
        Scan(&user.Id, &user.Email, &user.Name)
    return &user, err
}

func main() {
    db, _ := pgx.Connect(context.Background(), "postgres://...")
    lis, _ := net.Listen("tcp", ":50051")
    grpcServer := grpc.NewServer()
    pb.RegisterUserServiceServer(grpcServer, &UserServer{db: db})
    grpcServer.Serve(lis)
}
```

**Catalog Service** (movies, showtimes):
```go
// catalog-service/main.go
type CatalogServer struct {
    db *pgx.Conn
}

func (s *CatalogServer) GetShowtime(ctx context.Context, req *pb.GetShowtimeRequest) (*pb.Showtime, error) {
    var showtime pb.Showtime
    err := s.db.QueryRow(ctx,
        "SELECT id, movie_id, theater, time FROM showtimes WHERE id = $1",
        req.ShowtimeId).
        Scan(&showtime.Id, &showtime.MovieId, &showtime.Theater, &showtime.Time)
    return &showtime, err
}

func (s *CatalogServer) GetAvailableSeats(req *pb.GetAvailableSeatsRequest,
    stream grpc.ServerStream) error {
    rows, _ := s.db.Query(context.Background(),
        `SELECT row, col FROM seats WHERE showtime_id = $1 AND available = true`,
        req.ShowtimeId)
    defer rows.Close()

    for rows.Next() {
        var row, col int
        rows.Scan(&row, &col)
        stream.Send(&pb.Seat{Row: int32(row), Col: int32(col)})
    }
    return nil
}

func main() {
    db, _ := pgx.Connect(context.Background(), "postgres://...")
    lis, _ := net.Listen("tcp", ":50052")
    grpcServer := grpc.NewServer()
    pb.RegisterCatalogServiceServer(grpcServer, &CatalogServer{db: db})
    grpcServer.Serve(lis)
}
```

**Booking Service** (reservations, orchestrates booking saga):
```go
// booking-service/main.go
type BookingServer struct {
    db               *pgx.Conn
    userClient       pb.UserServiceClient
    catalogClient    pb.CatalogServiceClient
    paymentClient    pb.PaymentServiceClient
}

func (s *BookingServer) CreateBooking(ctx context.Context, req *pb.CreateBookingRequest) (*pb.CreateBookingResponse, error) {
    // Step 1: Verify user exists (call UserService)
    user, err := s.userClient.GetUser(ctx, &pb.GetUserRequest{Id: req.UserId})
    if err != nil {
        return nil, status.Errorf(codes.NotFound, "user not found")
    }

    // Step 2: Verify showtime exists (call CatalogService)
    showtime, err := s.catalogClient.GetShowtime(ctx, &pb.GetShowtimeRequest{ShowtimeId: req.ShowtimeId})
    if err != nil {
        return nil, status.Errorf(codes.NotFound, "showtime not found")
    }

    // Step 3: Reserve seat (local transaction)
    tx, _ := s.db.Begin(ctx)
    defer tx.Rollback(ctx)

    var seatId string
    err = tx.QueryRow(ctx,
        `UPDATE seats SET available = false, reserved_by = $1
         WHERE showtime_id = $2 AND row = $3 AND col = $4 AND available = true
         RETURNING id`,
        req.UserId, req.ShowtimeId, req.SeatRow, req.SeatCol).
        Scan(&seatId)
    if err != nil {
        return nil, status.Errorf(codes.FailedPrecondition, "seat not available")
    }

    // Step 4: Create booking record
    var bookingId string
    err = tx.QueryRow(ctx,
        `INSERT INTO bookings (user_id, showtime_id, seat_id, status, created_at)
         VALUES ($1, $2, $3, 'pending', NOW()) RETURNING id`,
        req.UserId, req.ShowtimeId, seatId).
        Scan(&bookingId)

    // Step 5: Process payment (call PaymentService, async or sync based on policy)
    paymentResp, err := s.paymentClient.ProcessPayment(ctx, &pb.ProcessPaymentRequest{
        BookingId: bookingId,
        UserId: req.UserId,
        Amount: showtime.Price,
        Currency: "USD",
    })

    if err != nil {
        // Compensation: release seat
        tx.Exec(ctx, "UPDATE seats SET available = true WHERE id = $1", seatId)
        tx.Rollback(ctx)
        return nil, status.Errorf(codes.Internal, "payment failed")
    }

    // Step 6: Confirm booking
    err = tx.QueryRow(ctx,
        `UPDATE bookings SET status = 'confirmed', transaction_id = $1 WHERE id = $2 RETURNING status`,
        paymentResp.TransactionId, bookingId).
        Scan(&struct{}{})

    tx.Commit(ctx)

    return &pb.CreateBookingResponse{
        BookingId: bookingId,
        Status: "confirmed",
    }, nil
}

func main() {
    db, _ := pgx.Connect(context.Background(), "postgres://...")

    // gRPC clients to other services
    userConn, _ := grpc.Dial("user-service:50051")
    catalogConn, _ := grpc.Dial("catalog-service:50052")
    paymentConn, _ := grpc.Dial("payment-service:50053")

    userClient := pb.NewUserServiceClient(userConn)
    catalogClient := pb.NewCatalogServiceClient(catalogConn)
    paymentClient := pb.NewPaymentServiceClient(paymentConn)

    server := &BookingServer{
        db: db,
        userClient: userClient,
        catalogClient: catalogClient,
        paymentClient: paymentClient,
    }

    lis, _ := net.Listen("tcp", ":50054")
    grpcServer := grpc.NewServer()
    pb.RegisterBookingServiceServer(grpcServer, server)
    grpcServer.Serve(lis)
}
```

**Payment Service** (processes payments):
```go
// payment-service/main.go
type PaymentServer struct {
    db *pgx.Conn
}

func (s *PaymentServer) ProcessPayment(ctx context.Context, req *pb.ProcessPaymentRequest) (*pb.ProcessPaymentResponse, error) {
    // Step 1: Charge credit card (call external payment gateway)
    txnId, err := chargeCard(ctx, req.UserId, req.Amount)
    if err != nil {
        return nil, status.Errorf(codes.Internal, "charge failed: %v", err)
    }

    // Step 2: Record transaction
    _, err = s.db.Exec(ctx,
        `INSERT INTO transactions (id, booking_id, user_id, amount, status)
         VALUES ($1, $2, $3, $4, 'completed')`,
        txnId, req.BookingId, req.UserId, req.Amount)

    return &pb.ProcessPaymentResponse{
        TransactionId: txnId,
        Success: true,
    }, nil
}

func chargeCard(ctx context.Context, userId string, amount float64) (string, error) {
    // Call Stripe, Square, etc.
    // Return transaction ID
    return "txn-" + uuid.NewString(), nil
}

func main() {
    db, _ := pgx.Connect(context.Background(), "postgres://...")
    lis, _ := net.Listen("tcp", ":50053")
    grpcServer := grpc.NewServer()
    pb.RegisterPaymentServiceServer(grpcServer, &PaymentServer{db: db})
    grpcServer.Serve(lis)
}
```

### API Gateway (Orchestration)
```go
// api-gateway/main.go
type Gateway struct {
    bookingClient pb.BookingServiceClient
}

func (g *Gateway) CreateBookingHTTP(w http.ResponseWriter, r *http.Request) {
    var req struct {
        UserId     string `json:"user_id"`
        ShowtimeId string `json:"showtime_id"`
        SeatRow    int    `json:"seat_row"`
        SeatCol    int    `json:"seat_col"`
    }
    json.NewDecoder(r.Body).Decode(&req)

    resp, err := g.bookingClient.CreateBooking(r.Context(), &pb.CreateBookingRequest{
        UserId: req.UserId,
        ShowtimeId: req.ShowtimeId,
        SeatRow: int32(req.SeatRow),
        SeatCol: int32(req.SeatCol),
    })

    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(resp)
}

func main() {
    conn, _ := grpc.Dial("booking-service:50054")
    bookingClient := pb.NewBookingServiceClient(conn)

    gateway := &Gateway{bookingClient: bookingClient}

    http.HandleFunc("POST /bookings", gateway.CreateBookingHTTP)
    http.ListenAndServe(":8080", nil)
}
```

## Trade-offs & Anti-Patterns

### What Breaks

**1. Distributed Monolith** (All the coupling, none of the benefits)
```
Services exist on paper but share a database
Deploying UserService requires testing BookingService
Changes to user schema lock the whole system
```
Fix: Enforce database-per-service immediately.

**2. Chatty Services** (100 RPCs to process one request)
```
BookingService → UserService → PreferenceService → NotificationService
Each hop adds 10ms latency. Total: 40ms.
10,000 RPS = 400 RPS total capacity (100ms * 10K = 1B nanoseconds)
```
Fix: Batch operations, denormalize data, use async messaging for non-critical dependencies.

**3. Cascading Failures**
```
PaymentService is slow
BookingService times out waiting for PaymentService
API Gateway times out waiting for BookingService
Entire system appears down
```
Fix: Implement circuit breakers, timeouts, fallbacks (covered in Resilience Patterns).

**4. Nano-Services** (Too many, too small)
```
Each endpoint is its own service
10 services to create a booking
Distributed complexity with no benefit
```
Fix: A service should have at least 5-10 endpoints and serve 1-2 business capabilities.

**5. Wrong Service Boundaries** (Based on technology, not business)
```
DatabaseService, CacheService, LoggingService as separate microservices
These are libraries, not domains
Causes infinite cross-service calls
```
Fix: Boundaries follow business domains, not infrastructure layers.

### Anti-Patterns to Avoid

- **Shared database across services**: Kills independent scalability and deployment
- **REST for internal service-to-service calls**: gRPC is 100x faster for high-frequency calls
- **No idempotency keys**: Retries cause duplicates
- **Ignoring eventual consistency**: Microservices are eventually consistent; UI must reflect this
- **Too many synchronous calls**: One slow service ruins everything

## Interview Corner

**Q1: How do you decide when to split a monolith into microservices?**

A: Microservices solve deployment and scalability problems, not complexity problems. Split when:
1. **Deployment coupling**: Different teams can't ship independently
2. **Resource contention**: One feature bottlenecks another (seat search blocking payment processing)
3. **Scaling mismatches**: User queries scale differently than payment processing
4. **Technology misalignment**: Different services need different tech stacks

Red flags: Fewer than 10,000 RPS, one team, single database—stay monolithic.

**Q2: Explain the strangler fig pattern.**

A: Instead of a big rewrite, grow microservices beside the monolith. An API gateway routes requests: "payments" → new PaymentService, everything else → monolith. Over time, the monolith "strrangles" (is replaced). Benefits: zero-downtime migration, incremental risk reduction, teams keep shipping.

**Q3: How do you handle cross-service queries without a shared database?**

A: Three approaches:
1. **Synchronous call**: BookingService calls UserService API. Simple but latency-sensitive.
2. **Denormalization**: BookingService maintains a cache of user data, updated via events. BookingService's "users" table is eventually consistent.
3. **Search index**: Elasticsearch has all data; use for analytics and cross-service queries, not operational.

Choose based on consistency requirements and latency.

**Q4: gRPC vs. REST for microservices?**

A: gRPC for internal, high-frequency calls (lower latency, binary, multiplexing). REST for external APIs and infrequent calls. gRPC streaming is powerful for paginated results or real-time data.

Trade-off: gRPC is harder to debug (binary protocol) but vastly faster. HTTP/2 multiplexing eliminates connection pooling complexity.

**Q5: What's the difference between a domain event and an integration event?**

A: Domain event: Something happened *within* a service (ReservationCreated). Used for coordinating logic *within* the service. Integration event: Published to other services (Kafka topic). Used for cross-service communication. Some domain events become integration events, but not all.

**Q6: Design a movie booking system. Where do you split the services? Why?**

A: **By business capability:**
- **UserService**: Authentication, profiles
- **CatalogService**: Movies, showtimes (independent scaling for search traffic)
- **BookingService**: Reservations, seat holds
- **PaymentService**: Transactions, refunds (isolated failure domain)

Why: Each scales differently. Catalog gets search traffic; Payment needs PCI compliance isolation. Teams own their data. BookingService depends on Catalog and Payment synchronously (seat availability, payment success), but User calls are cached.

**Q7: How do you prevent cascading failures in microservices?**

A: Circuit breakers, timeouts, bulkheads, fallbacks, retries with exponential backoff. If PaymentService is down, BookingService returns 503 "Service Temporarily Unavailable" instead of timing out. Client retries. Seat reservation is rolled back.

### Service Mesh Deep Dive: When and Why

A service mesh (Istio, Linkerd) adds significant operational complexity. Understand the trade-off:

**What a service mesh provides:**
1. **Automatic mTLS**: Every inter-service call is encrypted and authenticated without code changes
2. **Circuit breakers at infrastructure level**: Set once, applies to all services
3. **Automatic retries and timeouts**: Configured per service pair
4. **Distributed tracing**: Every RPC traced without instrumentation code
5. **Traffic splitting**: Canary deployments (route 10% to new version)

**Cost:**
- ~10-15ms latency added per hop (sidecar proxy overhead)
- Complex debugging (requests flow through proxies)
- Operational expertise required (k8s + Istio is steep learning curve)
- More resources consumed (sidecar per pod)

**When to adopt:**
- 10+ services already in production
- Need sophisticated traffic management
- Team has k8s expertise
- Regulatory requirements for mTLS

**When to skip:**
- First 5 services
- Running on VMs (service mesh designed for k8s)
- Small team without k8s ops expertise

### Testing Microservice Architectures

**Contract Testing**: Verify that ServiceA's client can communicate with ServiceB's server
```go
// booking_test.go
func TestBookingServiceCallsPaymentService(t *testing.T) {
    // Mock PaymentService
    paymentServer := grpc.NewServer()
    pb.RegisterPaymentServiceServer(paymentServer, &MockPaymentServer{})

    // Start mock server
    lis, _ := net.Listen("tcp", "localhost:0")
    go paymentServer.Serve(lis)
    defer paymentServer.Stop()

    // BookingService connects to mock
    bookingService := &BookingService{
        paymentClient: connectToMock(lis.Addr()),
    }

    // Test: Make sure booking calls payment with correct schema
    err := bookingService.CreateBooking(ctx, &CreateBookingRequest{...})
    assert.NoError(t, err)
    assert.Equal(t, 1, mockPaymentServer.ChargeCallCount)
}
```

**Integration Testing**: Multiple services in Docker Compose
```yaml
# docker-compose.test.yml
services:
  user-service:
    build: ./user-service
    ports: ["50051:50051"]

  booking-service:
    build: ./booking-service
    ports: ["50054:50054"]
    depends_on:
      - user-service
    environment:
      USER_SERVICE_ADDR: user-service:50051

  payment-service:
    build: ./payment-service
    ports: ["50053:50053"]
```

**Chaos Engineering**: Intentionally break things
```go
// Introduce 20% random failures in PaymentService
type ChaosPaymentService struct {
    delegate pb.PaymentServiceServer
}

func (c *ChaosPaymentService) ProcessPayment(ctx context.Context, req *pb.ProcessPaymentRequest) (*pb.ProcessPaymentResponse, error) {
    if rand.Intn(100) < 20 {  // 20% failure rate
        return nil, status.Error(codes.Internal, "simulated failure")
    }
    return c.delegate.ProcessPayment(ctx, req)
}
```

### Advanced: Cross-Service Transaction Consistency

**The Two-Service Consistency Problem**
```
Transaction: Transfer money from Account A to Account B (different services)

AccountService.Debit(A, $100)  // Success
WalletService.Credit(B, $100)  // Fails

Result: Money lost
```

Solutions ranked by complexity:

1. **Ignore and accept loss** (most systems do this)
   - Acceptable for small amounts
   - Analytics data being wrong is acceptable
   - Recommendation: Use for non-critical operations

2. **Eventual consistency + compensation**
   - AccountService: Debit succeeded
   - WalletService: Credit fails
   - Background job: Detects mismatch, compensates (credits wallet later)
   - Recommendation: Use for most cases

3. **Distributed transaction (saga)**
   - Saga coordinates the operations
   - Can rollback both if either fails
   - Recommendation: Use for financial transactions

4. **Shared database** (defeats microservices)
   - Both operations in one transaction
   - Simple but breaks service independence

### Interview Corner - Advanced Questions

**Q8: You have 10 services, all calling each other. How do you prevent cascading failures?**

A: Multiple layers:
1. **Timeout everywhere** (5-30 seconds depending on criticality)
2. **Circuit breakers** per service pair (if PaymentService fails 5x, stop calling for 60s)
3. **Bulkheads** per service (PaymentService max 50 concurrent, BookingService max 100)
4. **Rate limiting** at API gateway (100 RPS total, 10 RPS per user)
5. **Health checks** (liveness: restart if dead, readiness: remove from LB if not ready)
6. **Load shedding**: Reject requests with HTTP 503 if overloaded

Order matters: Timeout → Circuit Breaker → Bulkhead → Rate Limiting → Load Shedding

**Q9: A new junior engineer splits a service incorrectly. How do you identify and fix it?**

A: Signs of wrong boundaries:
- One service constantly calls another (tight coupling, should be one service)
- Services share data model (database-per-service violated)
- A service has inconsistent responsibilities (users AND payments)
- Cross-service transactions fail often (eventual consistency hard)

Fix approach:
1. Identify the root cause (wrong aggregate boundary)
2. Merge services back together (consolidate to monolith temporarily)
3. Re-decompose correctly along business boundaries
4. Use strangler fig pattern if many callers
5. Iterate (splitting is not one-time decision, refactor as you learn)

**Q10: Design microservices for a video streaming platform.**

A:
- **UserService**: Authentication, profiles, subscriptions
- **CatalogService**: Video metadata, search, recommendations
- **StreamingService**: Video encoding, CDN integration, bitrate adaptation
- **PaymentService**: Subscriptions, billing
- **AnalyticsService**: View counts, user behavior
- **NotificationService**: Emails, notifications
- **WatchlistService**: User's watch history, watchlist

Communication:
- UserService ← CatalogService (sync gRPC for recommendations)
- StreamingService ← CatalogService (sync gRPC for video metadata)
- PaymentService → Events (async Kafka for subscription changes)
- AnalyticsService ← Events (async Kafka for view events)

## Exercise

**Build a two-service system:**

1. **UserService** (gRPC): `GetUser(id)` returns user data with profile
2. **BookingService** (gRPC): Calls UserService, reserves a seat, returns booking details

Implement:
- gRPC server for UserService with PostgreSQL (profile lookup)
- gRPC server for BookingService that calls UserService (in same transaction)
- HTTP gateway that translates `POST /bookings` → gRPC call → returns booking summary
- Add logging interceptors to both services (log RPC method, latency)
- Implement one retry policy in the gateway (exponential backoff, max 3 retries)
- Add timeout handling (10 second overall timeout)

Testing:
- Test with `grpcurl` for gRPC: `grpcurl -d '{"id":"user-123"}' localhost:50051 user.UserService/GetUser`
- Test with `curl` for HTTP: `curl -X POST localhost:8080/bookings -d '{"user_id":"user-123", ...}'`
- Simulate failure: Kill UserService, verify BookingService returns error gracefully

Bonus:
- Add circuit breaker (stop calling UserService if 3 consecutive failures)
- Add metrics (request count, latency histogram)
- Add distributed tracing (correlation IDs across services)
- Implement health checks for both services
