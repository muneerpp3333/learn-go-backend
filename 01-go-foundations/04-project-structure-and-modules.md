# Project Structure and Modules: Building Maintainable Go Systems

## The Problem

There's no "one true way" to structure a Go project. The community has debated flat vs layered, monorepo vs polyrepo, and clean architecture vs pragmatism. Every choice has tradeoffs.

At senior backend roles, you must:
- Understand `go.mod` and semantic versioning for dependencies
- Know the difference between `/internal` and `/pkg` packages
- Design for clean architecture without over-engineering
- Work in monorepos and polyrepos
- Use build tags and ldflags for compile-time configuration
- Understand Go workspaces for multi-module development
- Avoid circular dependency hell
- Implement dependency injection without frameworks
- Write Makefiles that scale

This lesson covers Go's module system and proven architectural patterns from real-world systems.

## Theory: The Go Module System

### go.mod and go.sum: Dependency Management at Scale

When you create a Go project, you initialize a module:

```bash
go mod init github.com/moviebooking/api
```

This creates `go.mod`, the source of truth for your dependencies:

```
module github.com/moviebooking/api

go 1.21

require (
	github.com/jackc/pgx/v5 v5.5.0
	github.com/google/uuid v1.4.0
	github.com/grpc-ecosystem/go-grpc-middleware/v2 v2.0.1
)

require (
	github.com/jackc/pgpassfile v1.0.0 // indirect
	github.com/jackc/pgservicefile v0.0.0-20221227161230-091c0ba34f0a // indirect
)

exclude (
	github.com/jackc/pgx/v5 v5.6.0  // Known bad version, skip it
)
```

**What each field means**:
- `module`: Your module's fully qualified name (internet domain-based). This is how others import your code.
- `go`: Minimum Go version. Older Go versions are rejected with a clear error.
- `require`: Direct dependencies your code imports. Only list what you actually use.
- `indirect`: Dependencies your dependencies need (transitive). Auto-managed by `go mod tidy`.
- `exclude`: Versions to skip. Useful when a dependency releases a broken version.
- `replace`: Local path or alternative version. For monorepos: `replace github.com/company/lib => ../lib`

When you run `go build` or `go test`, Go's module system:
1. Reads go.mod and determines all needed versions
2. Fetches modules from GOPROXY (default: proxy.golang.org, with fallbacks)
3. Verifies checksums against go.sum to detect tampering or corruption
4. Builds with exact versions specified

The `go.sum` file tracks checksums:

```
github.com/jackc/pgx/v5 v5.5.0 h1:xKd7nE9EJ...=
github.com/jackc/pgx/v5 v5.5.0/go.mod h1:Vf...=
github.com/jackc/pgpassfile v1.0.0 h1:qJ...=
github.com/jackc/pgpassfile v1.0.0/go.mod h1:Lr...=
```

Two lines per dependency version:
- Direct hash: SHA256 of the module's contents
- /go.mod hash: SHA256 of only the go.mod file

**Why two hashes?** Because go.mod and module contents can change independently (rare but possible in extreme cases). Checking both provides defense in depth.

**Why this matters**: You don't need to check in `vendor/` dependencies. `go.mod` and `go.sum` guarantee reproducible builds anywhere:

```bash
# Developer A builds
go mod download
go build

# CI builds
go mod download
go build

# Production builds
go mod download
go build

# All three get EXACT same versions. No "works on my machine" surprises.
```

**Reproducibility is critical at scale**:
- If version A works but version A+1 has a bug, your builds must use A forever (until you upgrade deliberately)
- If developer A uses version A but developer B's git checkout gets version A+1, they get different binaries
- In production, you must know exactly what version you're running

`go mod verify` checks that downloaded modules match go.sum:

```bash
go mod verify
# If tampering or corruption: "checksum mismatch"
# If all good: (no output)
```

### Semantic Versioning and Major Versions

Go modules use semantic versioning: `MAJOR.MINOR.PATCH`.

- `v1.2.3`: Version 1, patch 2.3
- `v2.0.0`: Incompatible with v1 (breaking change)

Go enforces a radical rule: **A package cannot break backward compatibility without changing its module path**. If you make breaking changes, you must create a new module:

```
github.com/moviebooking/api → v1.0.0
github.com/moviebooking/api/v2 → v2.0.0 (breaking changes)
github.com/moviebooking/api/v3 → v3.0.0 (more breaking changes)
```

**The discipline this enforces**:
- Users can stay on v1 forever without surprises
- Your breaking change forces explicit user action (update import path)
- No "v2 in v1" versioning nightmare

Example:

```go
// Old API (v1)
package api

func CreateBooking(userID string, seats []string) (*Booking, error) {
	// ...
}

// Breaking change → new major version
// go.mod: module github.com/moviebooking/api/v2

func CreateBooking(ctx context.Context, userID string, seats []string) (*Booking, error) {
	// Now requires context
}
```

Users still on v1 import: `import "github.com/moviebooking/api"`
Users on v2 import: `import "github.com/moviebooking/api/v2"`

Both can coexist in the same program.

### GOPROXY, GOSUMDB, and Dependency Resolution

The `GOPROXY` environment variable controls where Go fetches modules from:

```bash
GOPROXY=https://proxy.golang.org,direct
```

This tells Go: "First try proxy.golang.org (caches all public modules). If not found, fetch directly from source (git clone)."

The proxy provides several benefits:
1. **Caching**: If one dev downloads a module, it's cached for all others
2. **Availability**: If GitHub is down, the proxy still has the module
3. **Speed**: No git clone needed; just download a zip
4. **Verification**: Proxy checksums against the public sumdb

```bash
GOSUMDB=sum.golang.org
```

Go checks every module's checksum against this public database (by default, proxy.golang.org's transparency log) to detect tampering. This is a defense against:
- Malicious proxies that modify modules
- Man-in-the-middle attacks
- Corrupted downloads

**For private modules in a company**:

```bash
# Use company proxy, fall back to public, then git
GOPROXY=https://proxy.company.com,https://proxy.golang.org,direct

# Mark company modules as private
GOPRIVATE=github.com/company/*

# Skip sumdb for private modules (they're not in the public transparency log)
GOSUMDB=off
```

This architecture allows:
- Private modules in your company (only employees can fetch them)
- Public modules cached in your proxy
- Offline builds if everything is cached

**Practical setup for CI/CD**:

```bash
# ci-build.sh
export GOPROXY=https://proxy.company.com,https://proxy.golang.org,direct
export GOSUMDB=sum.golang.org
export GOPRIVATE=github.com/company/*

# Fetch all modules and verify checksums
go mod download
go mod verify

# Now build (will be fast, modules already cached locally)
go build
```

This ensures your CI builds don't depend on external networks being up.

### Internal Packages and Access Control

Go's package visibility is file-scoped (exported vs unexported). But to enforce organizational boundaries, use `internal/`:

```
myapp/
  internal/
    payment/
      gateway.go    # Only myapp can import this
    booking/
      service.go    # Only myapp can import this
  cmd/
    api/
      main.go       # Imports internal/booking, internal/payment
  go.mod
```

If external package tries:

```go
import "github.com/moviebooking/api/internal/booking"  // COMPILE ERROR
```

Go rejects it at compile time. This is not a convention or warning—it's a hard compile error. The Go team made this a language feature to enforce architectural boundaries.

**What to put in internal/**:
- Domain logic and business rules (service layer)
- Repository implementations (database-specific code)
- Infrastructure setup (connection pools, cache clients)
- Dependency injection wiring
- Internal data structures and DTOs
- Low-level utilities specific to this service

**What to put in pkg/ or at module root** (public):
- Public API that external modules import
- Client libraries for this service
- Reusable algorithms or utilities
- Anything you want external code to depend on

**Example: Payment gateway library with multiple implementations**

```
github.com/company/payments/
├── internal/
│   ├── stripe/
│   │   ├── charges.go    # Stripe API integration
│   │   └── client.go
│   ├── paypal/
│   │   └── client.go
│   └── retry/
│       └── backoff.go
├── gateway.go            # Public: type PaymentGateway interface
├── transaction.go        # Public: type Transaction struct
├── error.go              # Public: type PaymentError struct
└── go.mod
```

External code can import the public API:

```go
import "github.com/company/payments"
g := payments.NewGateway(payments.ProviderStripe, key)
```

But cannot (and Go prevents it):

```go
import "github.com/company/payments/internal/stripe"  // Compile error
```

This allows you to:
1. Change internal implementations (Stripe → Wise) without breaking external code
2. Keep API surface minimal while hiding complexity
3. Enforce clean separation between public contract and private implementation

### Standard Project Layout

The community-agreed layout (from golang-standards/project-layout):

```
myapp/
  cmd/
    api/
      main.go              # API server entry point
    worker/
      main.go              # Background worker entry point
  internal/
    booking/
      service.go           # Business logic
      repository.go        # Database access
      error.go             # Domain errors
    payment/
      gateway.go           # Payment processing
    middleware/
      logging.go           # HTTP middleware
  pkg/
    clients/
      stripe/
        client.go          # Public Stripe client
  api/
    openapi.yaml           # API specification
  migrations/
    001_create_tables.sql  # Database migrations
  tests/
    integration/
      booking_test.go      # Cross-service tests
  Makefile
  Dockerfile
  go.mod
  go.sum
  README.md
```

**Why this layout?**
- `cmd/`: Multiple entry points (API, CLI, worker)
- `internal/`: Domain logic not for export
- `pkg/`: Reusable packages that could be extracted
- Clear separation of concerns

### Clean Architecture / Hexagonal Architecture in Go: Layers and Boundaries

Clean architecture (also called hexagonal architecture) separates concerns into concentric layers. The innermost layers (business logic) don't depend on outer layers (HTTP, databases), making the code testable and flexible.

```
┌─────────────────────────────────────────┐
│       Delivery (HTTP, gRPC, CLI)        │  Depends on everything
├─────────────────────────────────────────┤
│     Use Cases (Service Layer)           │  Depends on entities + interfaces
├─────────────────────────────────────────┤
│    Entities (Domain Models, Errors)     │  Depends on nothing
├─────────────────────────────────────────┤
│   Interfaces (Repository, Gateway)      │  Contract layer
├─────────────────────────────────────────┤
│  External (DB, Cache, External API)     │  Implementations
└─────────────────────────────────────────┘

Layer Rules:
- Outer layers can depend on inner layers
- Inner layers CANNOT depend on outer layers
- All dependencies point INWARD
```

The key insight: **business logic is in the center and knows nothing about HTTP, SQL, or any framework**. This makes it:
- Testable: Test business logic without mocking HTTP
- Portable: Same logic works in CLI, HTTP, gRPC, etc.
- Flexible: Swap implementations (PostgreSQL → MongoDB) without touching business logic

In Go code with realistic complexity:

```go
// internal/booking/entity.go - Domain model (zero dependencies)
package booking

type Booking struct {
	ID string
	UserID string
	Seats []string
	TotalCents int
	CreatedAt time.Time
}

type BookingError struct {
	Code string
	Message string
	StatusCode int
}

// internal/booking/repository.go - Dependency interface
type Repository interface {
	SaveBooking(ctx context.Context, b *Booking) error
	GetBooking(ctx context.Context, id string) (*Booking, error)
	ListUserBookings(ctx context.Context, userID string) ([]Booking, error)
}

// internal/booking/service.go - Use case logic (depends on interfaces, not implementations)
type Service struct {
	repo Repository  // Depends on interface
	paymentGateway PaymentGateway  // Depends on interface
	logger *slog.Logger
}

func NewService(repo Repository, gateway PaymentGateway, logger *slog.Logger) *Service {
	return &Service{repo, gateway, logger}
}

// Business logic: NO database code, NO HTTP code
func (s *Service) CreateBooking(ctx context.Context, userID string, seatNums []string) (*Booking, error) {
	// Validate
	if len(seatNums) == 0 {
		return nil, &BookingError{Code: "INVALID_SEATS"}
	}

	// Charge payment (interface, could be Stripe, local, etc.)
	txn, err := s.paymentGateway.Charge(ctx, fmt.Sprintf("booking_%s", userID), len(seatNums)*1500)
	if err != nil {
		return nil, fmt.Errorf("payment failed: %w", err)
	}

	// Save booking (interface, could be PostgreSQL, MongoDB, etc.)
	booking := &Booking{
		ID: uuid.New().String(),
		UserID: userID,
		Seats: seatNums,
		TotalCents: len(seatNums) * 1500,
		CreatedAt: time.Now(),
	}
	if err := s.repo.SaveBooking(ctx, booking); err != nil {
		// Refund on failure
		_ = s.paymentGateway.Refund(ctx, txn.ID)
		return nil, fmt.Errorf("save booking: %w", err)
	}

	return booking, nil
}

// internal/repository/postgres/booking.go - Database implementation
type PostgresRepository struct {
	conn *pgx.Conn
}

func (pr *PostgresRepository) SaveBooking(ctx context.Context, b *Booking) error {
	_, err := pr.conn.Exec(ctx, `
		INSERT INTO bookings (id, user_id, seats, total_cents, created_at)
		VALUES ($1, $2, $3, $4, $5)
	`, b.ID, b.UserID, b.Seats, b.TotalCents, b.CreatedAt)
	return err
}

// internal/api/handler/booking.go - HTTP delivery layer
type BookingHandler struct {
	service *booking.Service
}

func (h *BookingHandler) CreateBooking(w http.ResponseWriter, r *http.Request) {
	// Parse HTTP request
	var req struct {
		UserID string `json:"user_id"`
		Seats []string `json:"seats"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		return
	}

	// Call business logic (service)
	booking, err := h.service.CreateBooking(r.Context(), req.UserID, req.Seats)
	if err != nil {
		var bookErr *booking.BookingError
		if errors.As(err, &bookErr) {
			w.WriteHeader(bookErr.StatusCode)
			json.NewEncoder(w).Encode(map[string]any{
				"error": bookErr.Code,
				"message": bookErr.Message,
			})
			return
		}

		w.WriteHeader(http.StatusInternalServerError)
		return
	}

	// Return HTTP response
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(booking)
}

// cmd/api/main.go - Wiring (composition root)
func main() {
	// Database
	conn, _ := pgx.Connect(context.Background(), os.Getenv("DATABASE_URL"))
	repo := postgres.NewBookingRepository(conn)

	// External services
	gateway := stripe.NewGateway(os.Getenv("STRIPE_KEY"))

	// Business logic
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	service := booking.NewService(repo, gateway, logger)

	// HTTP delivery
	handler := &api.BookingHandler{service: service}

	// Register HTTP routes
	http.HandleFunc("POST /bookings", handler.CreateBooking)

	http.ListenAndServe(":8080", nil)
}
```

**The power of this structure**:
1. **Testing**: Test `Service.CreateBooking()` with a mock `Repository` and mock `PaymentGateway`. No HTTP, no database.
2. **Flexibility**: Replace `PostgresRepository` with `MongoRepository`, same service code.
3. **Clarity**: Anyone reading `Service` knows it's pure business logic.
4. **Reusability**: Same `Service` works in HTTP, gRPC, CLI, background jobs.

**Common mistake**: Mixing layers. A handler that directly queries the database:

```go
// BAD: Handler doing database work
func BadCreateBooking(w http.ResponseWriter, r *http.Request) {
	conn := getDBConnection()  // Where's this from?
	rows, _ := conn.Query("SELECT * FROM seats ...")  // Database logic in HTTP handler
	// ...
}

// GOOD: Handler calls service
func GoodCreateBooking(h *Handler) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		booking, _ := h.service.CreateBooking(r.Context(), ...)  // Service handles DB
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(booking)
	}
}
```

### Dependency Injection Without Frameworks

Go doesn't need DI frameworks (unlike Java/C#). Manual wiring is often clearer:

```go
// pkg/container/container.go - All dependencies in one place
type Container struct {
	db *pgx.Conn
	bookingService *booking.Service
	paymentGateway payment.Gateway
	logger *slog.Logger
}

func NewContainer(ctx context.Context) (*Container, error) {
	// Initialize in dependency order
	db, err := pgx.Connect(ctx, os.Getenv("DATABASE_URL"))
	if err != nil {
		return nil, fmt.Errorf("connect db: %w", err)
	}

	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))

	bookingRepo := postgres.NewBookingRepository(db)
	paymentGateway := stripe.NewGateway(os.Getenv("STRIPE_KEY"))

	bookingService := booking.NewService(bookingRepo, paymentGateway, logger)

	return &Container{
		db: db,
		bookingService: bookingService,
		paymentGateway: paymentGateway,
		logger: logger,
	}, nil
}

// cmd/api/main.go
func main() {
	c, err := container.NewContainer(context.Background())
	if err != nil {
		log.Fatal(err)
	}

	// Use c.bookingService everywhere
	http.HandleFunc("/bookings", func(w http.ResponseWriter, r *http.Request) {
		// c.bookingService.CreateBooking(...)
	})
}
```

**Alternative: Wire (code generation)**:

If your graph is large, use `google/wire`:

```go
// pkg/container/wire.go
func InitializeContainer() (*Container, error) {
	wire.Build(
		newDB,
		newLogger,
		postgres.NewBookingRepository,
		stripe.NewGateway,
		booking.NewService,
		newContainer,
	)
	return nil, nil
}

// wire_gen.go (auto-generated)
func InitializeContainer() (*Container, error) {
	// Compiler generates the correct initialization order
}
```

## Production Code: Complete Movie Booking Service Structure

```
moviebooking/
├── cmd/
│   ├── api/
│   │   └── main.go            # HTTP API server
│   └── worker/
│       └── main.go            # Background payment processor
├── internal/
│   ├── booking/
│   │   ├── entity.go          # Domain: Booking, Seat
│   │   ├── repository.go      # Interface: BookingRepository
│   │   ├── service.go         # Business logic
│   │   └── error.go           # Domain errors
│   ├── payment/
│   │   ├── gateway.go         # Interface: PaymentGateway
│   │   └── error.go           # Payment errors
│   ├── postgres/
│   │   ├── booking.go         # BookingRepository impl
│   │   ├── migrations.go      # Schema updates
│   │   └── connection.go      # Connection pool
│   ├── stripe/
│   │   └── gateway.go         # PaymentGateway impl
│   ├── api/
│   │   ├── handler/
│   │   │   └── booking.go     # HTTP handlers
│   │   └── middleware/
│   │       └── logging.go     # Request logging
│   ├── queue/
│   │   └── payment_jobs.go    # Job queue for payments
│   └── container/
│       └── wire.go            # Dependency injection
├── migrations/
│   ├── 001_create_tables.sql
│   └── 002_add_indexes.sql
├── Makefile
├── Dockerfile
├── go.mod
├── go.sum
└── README.md

// Makefile
.PHONY: build test run migrate

build:
	go build -ldflags="-X main.Version=$(git describe --tags)" -o bin/api ./cmd/api
	go build -o bin/worker ./cmd/worker

test:
	go test -v -race -cover ./...

run:
	DATABASE_URL=postgres://localhost go run ./cmd/api

migrate:
	go run ./internal/postgres/migrations.go up

lint:
	golangci-lint run ./...
```

## Build Tags and ldflags: Compile-Time Configuration

**Build tags** (also called build constraints) conditionally include files at compile time:

```go
// internal/payment/stripe_live.go
//go:build live
// +build live

package payment

var StripeAPIKey = os.Getenv("STRIPE_LIVE_KEY")
var StripeEndpoint = "https://api.stripe.com"

// internal/payment/stripe_test.go (no tag = default)
//go:build !live
// +build !live

package payment

var StripeAPIKey = "sk_test_4242424242424242"
var StripeEndpoint = "https://api.stripe.test"

// Compile for production with live credentials
go build -tags=live -o bin/api ./cmd/api

// Compile for testing (default) with test credentials
go build -o bin/api ./cmd/api
```

Tags control conditional compilation:
- `//go:build live` = include only when `-tags=live` is passed
- `//go:build !live` = include when `-tags=live` is NOT passed
- Multiple tags: `//go:build (linux || darwin) && !race`

Use cases:
1. Different configurations (live vs test vs staging)
2. Platform-specific code (Windows vs Linux)
3. Optional features (with or without cgo)
4. Different storage backends (only compile one)

**ldflags** (linker flags) inject values at link time without recompiling:

```bash
VERSION=$(git describe --tags)
BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)
COMMIT=$(git rev-parse HEAD)
BUILD_HOSTNAME=$(hostname)

go build \
  -ldflags="\
    -X main.Version=$VERSION \
    -X main.BuildTime=$BUILD_TIME \
    -X main.Commit=$COMMIT \
    -X main.BuildHostname=$BUILD_HOSTNAME" \
  -o bin/api \
  ./cmd/api
```

In main.go:

```go
package main

import "fmt"

var (
	Version = "unknown"
	BuildTime = "unknown"
	Commit = "unknown"
	BuildHostname = "unknown"
)

func main() {
	fmt.Printf("api version=%s\n", Version)
	fmt.Printf("built at=%s\n", BuildTime)
	fmt.Printf("commit=%s\n", Commit)
	fmt.Printf("builder=%s\n", BuildHostname)

	// Output:
	// api version=v1.2.3
	// built at=2026-03-26T12:34:56Z
	// commit=abc123def456
	// builder=ci-builder-1
}
```

**Why ldflags instead of rebuilding?** Because:
- Version changes don't require recompilation (just relinking)
- Build info is injected at release time, not development time
- Same binary can have different version strings

**Production setup**:

```bash
#!/bin/bash
# build.sh

VERSION=$(git describe --tags --always)
COMMIT=$(git rev-parse HEAD)
DIRTY=$(git diff --quiet || echo "-dirty")
BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)

LDFLAGS="-X main.Version=${VERSION}${DIRTY} -X main.Commit=${COMMIT} -X main.BuildTime=${BUILD_TIME}"

go build -ldflags="$LDFLAGS" -o bin/api ./cmd/api
```

This ensures every binary reports exactly what version and commit it was built from.

## Go Workspaces: Multi-Module Development (Go 1.18+)

For a monorepo with multiple modules, `go.work` coordinates them locally:

```
company/
├── go.work          # Workspace definition (local only, don't commit to git!)
├── service-a/
│   ├── go.mod       # Module github.com/company/service-a
│   ├── go.sum
│   └── cmd/api/main.go
├── service-b/
│   ├── go.mod       # Module github.com/company/service-b
│   └── cmd/worker/main.go
└── shared/
    ├── go.mod       # Module github.com/company/shared (private)
    └── auth/auth.go
```

The `go.work` file tells Go to use local modules instead of downloading from GOPROXY:

```
// go.work
go 1.21

use (
	./service-a
	./service-b
	./shared
)

// This means:
// - When service-a tries to import github.com/company/shared,
//   Go uses ./shared instead of downloading from proxy
// - Changes to ./shared are immediately visible in service-a
// - You can test coordinated changes before releasing shared v1.2.4
```

**Workflow**:

```bash
# Clone the monorepo
git clone https://github.com/company/services
cd services

# go.work is NOT in git (add to .gitignore)
echo "go.work" >> .gitignore

# Developer creates it locally
go work init ./service-a ./service-b ./shared

# Now:
cd service-a
go test ./...  # Uses local ./shared, not proxy

# Make a change to shared
cd ../shared
echo "// new feature" >> auth/auth.go

# service-a tests immediately see the change
cd ../service-a
go test ./...  # Uses updated ./shared

# When you're confident, release shared
cd ../shared
git tag v1.2.4
git push --tags

# Update go.mod files to use the new version
# Remove go.work
rm go.work
```

**Without `go.work`, you'd need `replace` directives**:

```
// service-a/go.mod (old way, pre-Go 1.18)
module github.com/company/service-a

require github.com/company/shared v1.2.3

// For local development, add replace:
replace github.com/company/shared => ../shared

// Problem: this go.mod can't be committed (replace directive)
// You must remove it before pushing to git
```

`go.work` is cleaner because it's local only. Never commit it to git.

## Circular Dependencies and Module Organization: The Enforcer of Clean Architecture

Go's import system forbids circular imports at compile time. This is a *feature*, not a limitation:

```
package a imports b
package b imports a
// COMPILE ERROR: import cycle not allowed
```

This forces you to design systems without cycles. Cycles indicate poor architecture. If you hit a cycle, Go forces you to fix it.

**Example: Common cycle mistake**

```
api/
  handler.go imports "internal/booking"
  handler.go imports "internal/api"  (wrong!)

internal/
  booking/service.go imports "internal/api"  (wrong!)
  booking/service.go imports "internal/error"

// Try to compile:
// import cycle not allowed:
//   api -> internal/booking -> internal/api -> (back to api)
```

**Solutions**:

**1. Extract shared interface to a new package**:

```
internal/
  booking/entity.go (domain model, zero imports)
  booking/service.go (imports "internal/booking/entity")
  api/error.go (error types, zero imports)

Now no cycle: booking doesn't import api, they're independent
```

**2. Move types to a shared location**:

```
Before:
a/handler.go imports b/entities
b/entities imports a/error  // Cycle!

After:
domain/booking.go (shared types)
a/handler.go imports "domain"
b/entities.go imports "domain"
```

**3. Dependency inversion**:

```
Before:
api/handler imports "internal/booking"
booking/service imports "internal/api/error"  // Can't! Creates cycle

After:
booking/service imports "internal/booking/error"  (in same package)
api/handler imports "internal/booking" and "internal/booking/error"  (api depends down, not up)
```

The constraint of no circular imports ensures that your code has a clear dependency direction: outer layers depend on inner layers, never the reverse.

## Monorepo vs Polyrepo for Microservices

**Monorepo**: All services in one repository

```
company/
  go.work
  go.mod
  service-a/
    go.mod
    cmd/api/main.go
    internal/...
  service-b/
    go.mod
    cmd/api/main.go
    internal/...
  shared/
    go.mod
    pkg/auth/...
    pkg/logging/...
```

Advantages:
- Shared code is easy (in one place)
- Coordinated releases (all services version together)
- Easier refactoring (change shared code, rebuild all)

Disadvantages:
- Huge repository (slow git clone)
- All services must use compatible Go versions
- One failure can block all services (CI/CD)
- Hard to enforce service boundaries

**Polyrepo**: Each service in its own repository

```
company/
  service-a/     (repo 1)
  service-b/     (repo 2)
  shared-lib/    (repo 3, imported via go.mod)
```

Advantages:
- Small repositories (fast operations)
- Independent versioning (service-a uses shared v1.0, service-b uses shared v2.0)
- Independent CI/CD (service-a failure doesn't block service-b)
- Clear boundaries (can't accidentally import internal code)

Disadvantages:
- Version coordination nightmare (which version of shared am I on?)
- Refactoring requires multiple PRs
- Shared library changes need coordination

**Recommendation for new projects**: Start with **polyrepo** (separate modules as you scale), but use a **shared private module** for common code:

```
company/
  api-server/      (go.mod: module github.com/company/api-server)
  worker/          (go.mod: module github.com/company/worker)
  shared-lib/      (go.mod: module github.com/company/shared, private)

Both api-server and worker:
  require github.com/company/shared v1.2.3
```

This gives you:
- Independent versioning for services
- Shared code that's under version control
- Clear boundaries (shared can't import from api-server)
- Polyrepo benefits without sacrificing shared code

## Module Proxies and Dependency Security

For enterprise deployments, you may want to control module sources with a private proxy:

```bash
GOPROXY=https://athens.my-company.com,https://proxy.golang.org,direct
GOSUMDB=off  # Don't check against public sumdb for private modules
```

Athens is an open-source module proxy that provides:
- Caching: all modules are cached locally, reducing external dependencies
- Allowlist/blocklist: enforce which modules are permitted
- Checksum verification: ensure modules haven't been tampered with
- Offline builds: once cached, builds work without external network

This is critical for:
1. **Compliance**: Some industries can't download random modules from the internet
2. **Security**: Scan all modules for vulnerabilities before they're used
3. **Availability**: If github.com is down, your builds still work
4. **Performance**: Local proxy is faster than downloading from external proxy

For smaller teams, the default setup is usually fine: GOPROXY=proxy.golang.org,direct uses the public proxy and falls back to git.

## Standard Go Project Layout and Best Practices

The golang-standards/project-layout repository documents the community's consensus on how to structure Go projects. Key principles:

1. **cmd/**: Binary entry points. Each subdirectory is one executable.
2. **internal/**: Code not for export. Only imports within the module can use it.
3. **pkg/**: Public packages. External modules can import and depend on this.
4. **api/**: API specifications (OpenAPI, proto files).
5. **migrations/**: Database migration scripts.
6. **Makefile**: Build automation for common tasks.

For a service, organize by domain, not by technical layer:

```
movie-booking/
├── internal/booking/          # All booking-related logic
├── internal/payment/          # All payment-related logic
├── internal/user/             # All user-related logic
```

Not:

```
movie-booking/
├── internal/service/          # All service files mixed together
├── internal/repository/       # All repository files mixed together
├── internal/handler/          # All handler files mixed together
```

Domain organization makes it easy to find related code and reason about dependencies. When you need to change payment behavior, all payment code is together. When a new developer joins, they can navigate by domain (payments, bookings, users) rather than by technical layer.

This lesson has covered Go's module system from first principles to production patterns. The key takeaway: Go's module system and project structure conventions exist to scale. Small projects don't care about them, but at 10+ developers or multiple services, these patterns prevent chaos and make refactoring possible. Use them early and consistently.

## Interview Corner: Common Questions and Answers

**Q1: What's in go.mod vs go.sum, and why do you commit both?**

A: `go.mod` lists your direct dependencies and Go version. `go.sum` contains checksums for every version of every module (direct and indirect, both .mod and full). Commit both so builds are reproducible. If `go.sum` is wrong, `go mod verify` catches it. Don't modify go.sum manually—let `go` commands manage it. go.sum acts as a lock file ensuring exact versions across all environments.

**Q1b: What happens if a dependency you use gets deleted from the internet?**

A: If the dependency is in your go.sum, Go's default proxy (proxy.golang.org) has cached it, so builds still work. The proxy acts as a permanent record. This is why committing go.sum is critical—without it, your builds depend on external modules existing forever. With it, you're safe even if GitHub removes the repo.

**Q2: You want to add a breaking change to your library. How do you do it without breaking users?**

A: Create a new major version: update `go.mod` from `module github.com/mylib` to `module github.com/mylib/v2`. Users on v1 import `github.com/mylib`; users on v2 import `github.com/mylib/v2`. Both can coexist in the same program. This forces users to explicitly opt in to breaking changes.

**Q3: Explain the internal/ directory. When should you use it?**

A: Go forbids importing packages under `internal/` from outside the module. `import "github.com/myapp/internal/payment"` is a compile error unless the importing code is within myapp. Use it for domain logic, implementation details, and low-level utilities you don't want to export. Use normal packages for reusable libraries.

**Q4: You have a monorepo with 10 services. Should you use one go.mod or ten?**

A: Ten go.mod files (separate modules) unless the services must share code. Separate modules: independent versioning, independent deployments, clear boundaries. Shared go.mod: shared build, harder to enforce boundaries, tight coupling. Use go.work for local development across modules.

**Q5: How do you inject dependencies without a framework?**

A: Constructor functions: `func NewBookingService(repo Repository, gateway PaymentGateway) *BookingService`. Create a container struct that holds all your singletons, initialize in main(), wire everything, then use. For large graphs, use google/wire for code generation. For microservices, each binary's main.go is simple DI code.

**Q6: A dependency has a security vulnerability. How do you update it?**

A: `go get -u github.com/vulnerable/lib@v1.2.3` (to a patched version), or `go get -u ./...` (to latest of everything). Run `go mod tidy` to clean up unused. Commit go.mod and go.sum. CI should run `go mod verify` to catch tampering.

**Q7: You want to use a private GitHub repo as a dependency. How?**

A: Add `github.com/company/private-lib` to go.mod (it'll fetch). Set up a personal access token: `git config --global url."https://PAT@github.com/".insteadOf "https://github.com/"`. Or use GOPROXY with authentication for private modules. For CI, use deploy keys.

**Q8: Explain clean architecture layers and give a project structure example.**

A: Layer by layer: delivery (HTTP/gRPC) → use cases (business logic) → entities (domain models) → interfaces (repository, gateway) → external (database, cache). Project structure: `cmd/` for entry points, `internal/` for domain logic and interfaces, implementations in subpackages. Business logic never imports `internal/api/handler` or `internal/postgres`—only the reverse.

**Q9: You're migrating from monolith to microservices. How do you structure shared code?**

A: Create a separate private module (github.com/company/shared) in its own repo. All services depend on it via go.mod require statements. Version it carefully—you can have service-a on shared v1.0 and service-b on shared v2.0 simultaneously. This gives you polyrepo benefits (independent deployments) while sharing code cleanly (no copy-paste).

**Q10: What's the biggest mistake in project structure?**

A: Putting everything in one flat package at the root level, or conversely, creating a package for every single type. Go packages should represent cohesive units of functionality. A booking package with service, repository, and entity all together is better than separate packages for each. The goal is to find the right granularity where related code is together and unrelated code is apart.

## What Breaks at Scale

1. **Circular dependencies**: Force bad architecture; split modules to fix. Go prevents them at compile time.
2. **Giant monolith in one package**: No boundaries, hard to navigate, easy to create circular dependencies.
3. **Ignoring GOPROXY**: Slow builds, network dependency, security risk. Use go.sum and proxy.golang.org.
4. **go.sum in .gitignore**: Builds aren't reproducible; vulnerability scanning fails. Always commit go.sum.
5. **Missing internal/**: No way to enforce API boundaries. External code shouldn't import your implementation.
6. **Massive god interfaces**: Hard to mock, forces implementers to do everything. Split into small, focused interfaces.
7. **No dependency injection**: Configuration scattered everywhere; hard to test. Wire in main(), not in packages.
8. **go.work checked into git**: Local-only file that breaks CI. Add to .gitignore always.
9. **All code in cmd/**: No separation of concerns. Move domain logic to internal/, delivery to cmd/.
10. **Inconsistent versioning**: Some services on v1.0 of shared, others on v2.0. Makes deployment confusing. Document version strategy.

## Exercise

**Exercise 1: Module versioning**

Create two versions of a library:
- v1: `type BookingService struct { Create(...) error }`
- v2: `type BookingService struct { Create(ctx context.Context, ...) error }`

Push both as separate modules (v1 and v2). Write an app that imports both and uses each.

**Exercise 2: Project structure**

Restructure a monolithic `main.go` into:
- `cmd/api/main.go`: API entry point
- `internal/booking/service.go`: Business logic
- `internal/postgres/booking.go`: Database layer
- Inject dependencies properly
- Move all database code out of main()

**Exercise 3: Internal packages**

Create a project with:
- `internal/domain/booking.go`: Domain model
- `internal/api/handler.go`: HTTP handler
- `pkg/client/client.go`: Public library

Try to import `internal/domain` from outside the module. Verify it fails at compile time.

**Exercise 4: Dependency injection**

Write a Container struct that initializes:
- Database connection
- Logger
- Repository implementation
- Service with injected repo

Wire everything in one place. Show how tests can inject a mock repository.

**Exercise 5: Build configuration**

Write main.go that accepts an ldflags variable for Version and prints it. Build twice:
- Once with default ("unknown")
- Once with `-ldflags="-X main.Version=v1.2.3"`

Verify both builds print different versions.

**Exercise 6: go.work Experimentation**

Create a monorepo with:
- service-a/go.mod and service-b/go.mod
- shared/go.mod with a public function
- Create go.work locally linking all three
- Modify shared and verify changes are visible in service-a tests without rebuilding
- Remove go.work and try to build—it fails until you update version requirements

**Exercise 7: Circular Dependency Detection**

Deliberately create a circular import and observe the compile error:
- package a imports b
- package b imports a
- Try to compile (fails with "import cycle")
- Fix by creating a third package c that both depend on

**Exercise 8: Monorepo vs Polyrepo Trade-offs**

Build the same service two ways:
- Monorepo: single go.mod with /service-a, /service-b, /shared
- Polyrepo: three separate repos (simulate with separate directories + replace directives)
- Compare repository size, build time, and ease of refactoring

