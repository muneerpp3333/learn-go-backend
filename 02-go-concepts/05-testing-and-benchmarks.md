# Testing and Benchmarks: Building Reliable Systems

## Problem: Testing Backend Services at Scale

You need to test:
- HTTP handlers with complex business logic
- Database operations with real queries
- Concurrent code without race conditions
- Performance-critical paths with benchmarks
- Production failures via fuzzing

The challenge: Go's testing philosophy is minimalist (no fancy frameworks), but you must master the built-in tools to write production-grade tests.

---

## Part 1: Table-Driven Tests

The Go standard for organizing test cases.

### Basic Pattern

```go
func TestAdd(t *testing.T) {
    tests := []struct {
        name      string
        a, b      int
        want      int
    }{
        {"positive", 1, 2, 3},
        {"negative", -1, -2, -3},
        {"zero", 0, 0, 0},
        {"large", 1e9, 1e9, 2e9},
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            got := Add(tt.a, tt.b)
            if got != tt.want {
                t.Errorf("Add(%d, %d) = %d; want %d", tt.a, tt.b, got, tt.want)
            }
        })
    }
}
```

Each test case is a struct with inputs, expected output, and a name. `t.Run()` creates subtests visible in output and `go test -v`.

### Complex Table-Driven Tests

```go
func TestBookingService(t *testing.T) {
    type args struct {
        userID   string
        movieID  string
        seatCount int
    }

    type want struct {
        success bool
        errMsg  string
    }

    tests := []struct {
        name string
        args args
        want want
    }{
        {
            name: "valid booking",
            args: args{userID: "u1", movieID: "m1", seatCount: 2},
            want: want{success: true},
        },
        {
            name: "invalid user",
            args: args{userID: "", movieID: "m1", seatCount: 2},
            want: want{success: false, errMsg: "invalid user"},
        },
        {
            name: "not enough seats",
            args: args{userID: "u1", movieID: "m1", seatCount: 1000},
            want: want{success: false, errMsg: "not enough seats"},
        },
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            service := setupTestService()
            err := service.Book(tt.args.userID, tt.args.movieID, tt.args.seatCount)

            if tt.want.success && err != nil {
                t.Fatalf("unexpected error: %v", err)
            }
            if !tt.want.success && err == nil {
                t.Fatalf("expected error, got nil")
            }
            if !tt.want.success && !strings.Contains(err.Error(), tt.want.errMsg) {
                t.Errorf("error = %v; want substring %q", err, tt.want.errMsg)
            }
        })
    }
}
```

### Running Specific Tests

```bash
# Run all tests
go test ./...

# Run specific test
go test -run TestBookingService ./...

# Run specific subtest
go test -run TestBookingService/valid_booking ./...

# Verbose output
go test -v ./...

# Show test coverage
go test -cover ./...

# Stop on first failure
go test -failfast ./...
```

---

## Part 2: Test Fixtures and Helpers

### t.Helper() for Cleaner Error Messages

```go
func setupBookingService(t *testing.T) *BookingService {
    t.Helper()  // Excludes this function from error line numbers

    db, err := pgx.Connect(context.Background(), dbConnString)
    if err != nil {
        t.Fatalf("failed to connect to database: %v", err)
    }

    return &BookingService{db: db}
}

func TestBook(t *testing.T) {
    service := setupBookingService(t)  // Error reported at this line, not inside setupBookingService
    // ...
}
```

Without `t.Helper()`, errors report from inside setupBookingService, making debugging harder.

### testdata Directory for Golden Files

```
mypackage/
├── myfile_test.go
└── testdata/
    ├── input.json
    ├── expected_output.json
    └── response.html
```

```go
func TestParseResponse(t *testing.T) {
    // Read golden file
    data, err := os.ReadFile("testdata/response.html")
    if err != nil {
        t.Fatal(err)
    }

    result, err := parseHTML(string(data))
    if err != nil {
        t.Fatalf("parseHTML failed: %v", err)
    }

    expected, _ := os.ReadFile("testdata/expected_output.json")
    if !bytes.Equal(mustMarshal(result), expected) {
        t.Errorf("output mismatch")
    }
}
```

Golden files are useful for:
- Large JSON payloads
- HTML/XML documents
- Expected output snapshots

### Custom Assertion Helpers

```go
func assertNoError(t *testing.T, err error) {
    t.Helper()
    if err != nil {
        t.Fatalf("unexpected error: %v", err)
    }
}

func assertEqual(t *testing.T, got, want interface{}) {
    t.Helper()
    if got != want {
        t.Errorf("got %v; want %v", got, want)
    }
}

// Usage
func TestBooking(t *testing.T) {
    service := setupService(t)
    err := service.Book("u1", "m1", 2)
    assertNoError(t, err)
    assertEqual(t, service.SeatCount(), 98)
}
```

---

## Part 3: HTTP Testing with httptest

### Testing HTTP Handlers

```go
func TestBookingHandler(t *testing.T) {
    handler := http.HandlerFunc(BookingHandler)

    // Create a request
    reqBody := `{"user_id": "u1", "movie_id": "m1", "seats": 2}`
    req := httptest.NewRequest(http.MethodPost, "/book", strings.NewReader(reqBody))
    req.Header.Set("Content-Type", "application/json")

    // Record response
    w := httptest.NewRecorder()
    handler.ServeHTTP(w, req)

    // Assert response
    if w.Code != http.StatusOK {
        t.Errorf("status = %d; want %d", w.Code, http.StatusOK)
    }

    var response map[string]string
    json.Unmarshal(w.Body.Bytes(), &response)
    if response["booking_id"] == "" {
        t.Error("booking_id is empty")
    }
}
```

### Testing HTTP Clients

```go
func TestClientWithMock(t *testing.T) {
    // Mock server
    server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        if r.URL.Path == "/cinema/c1" {
            w.Header().Set("Content-Type", "application/json")
            json.NewEncoder(w).Encode(map[string]int{"available": 50})
        }
    }))
    defer server.Close()

    // Test client with mock server
    client := NewCinemaClient(server.URL)
    available, err := client.GetAvailable(context.Background(), "c1")
    if err != nil {
        t.Fatalf("GetAvailable failed: %v", err)
    }

    if available != 50 {
        t.Errorf("available = %d; want 50", available)
    }
}
```

### Testing Middleware

```go
func TestLoggingMiddleware(t *testing.T) {
    // Capture log output
    var buf bytes.Buffer
    log.SetOutput(&buf)
    defer log.SetOutput(os.Stderr)

    // Inner handler
    handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        w.WriteHeader(http.StatusOK)
    })

    // Wrapped with middleware
    wrapped := loggingMiddleware(handler)

    req := httptest.NewRequest(http.MethodGet, "/test", nil)
    w := httptest.NewRecorder()

    wrapped.ServeHTTP(w, req)

    if !strings.Contains(buf.String(), "/test") {
        t.Error("logging middleware did not log request path")
    }
}
```

---

## Part 4: Integration Tests with Real Databases

### TestMain for Setup/Teardown

```go
var testDB *pgx.Pool

func TestMain(m *testing.M) {
    // Setup
    var err error
    testDB, err = pgx.NewPool(context.Background(), "postgres://test:test@localhost/testdb")
    if err != nil {
        log.Fatalf("failed to connect: %v", err)
    }

    // Migrate
    if err := migrate(testDB); err != nil {
        log.Fatalf("migration failed: %v", err)
    }

    // Run tests
    code := m.Run()

    // Teardown
    testDB.Close()
    os.Exit(code)
}

func TestInsertUser(t *testing.T) {
    if testDB == nil {
        t.Fatal("testDB not initialized")
    }

    var id string
    err := testDB.QueryRow(context.Background(),
        "INSERT INTO users (name) VALUES ($1) RETURNING id", "Alice").Scan(&id)
    if err != nil {
        t.Fatalf("insert failed: %v", err)
    }

    if id == "" {
        t.Error("id is empty")
    }
}
```

### Transaction Rollback Pattern

Avoid polluting test database by rolling back each test:

```go
func TestBooking(t *testing.T) {
    // Start transaction
    tx, err := testDB.Begin(context.Background())
    if err != nil {
        t.Fatalf("begin failed: %v", err)
    }
    defer tx.Rollback(context.Background())  // Rollback after test

    // All queries in this test use tx
    var bookingID string
    err = tx.QueryRow(context.Background(),
        "INSERT INTO bookings (user_id, movie_id) VALUES ($1, $2) RETURNING id",
        "u1", "m1").Scan(&bookingID)
    if err != nil {
        t.Fatalf("insert failed: %v", err)
    }

    if bookingID == "" {
        t.Error("booking_id is empty")
    }

    // After test, rollback ensures database is clean
}
```

### testcontainers-go for Docker Databases

```go
import "github.com/testcontainers/testcontainers-go"

func TestWithPostgres(t *testing.T) {
    ctx := context.Background()

    // Start postgres container
    req := testcontainers.ContainerRequest{
        Image:        "postgres:15",
        ExposedPorts: []string{"5432/tcp"},
        Env: map[string]string{
            "POSTGRES_USER":     "test",
            "POSTGRES_PASSWORD": "test",
            "POSTGRES_DB":       "testdb",
        },
    }

    container, err := testcontainers.GenericContainer(ctx, testcontainers.GenericContainerRequest{
        ContainerRequest: req,
        Started:          true,
    })
    if err != nil {
        t.Fatalf("failed to start container: %v", err)
    }
    defer container.Terminate(ctx)

    // Get connection string
    host, _ := container.Host(ctx)
    port, _ := container.MappedPort(ctx, "5432/tcp")
    connString := fmt.Sprintf("postgres://test:test@%s:%s/testdb", host, port.Port())

    // Connect and test
    db, err := pgx.Connect(ctx, connString)
    if err != nil {
        t.Fatalf("connect failed: %v", err)
    }
    defer db.Close(ctx)

    // Now run tests against real postgres
}
```

---

## Part 5: Benchmarking Deep Dive

### Basic Benchmark

```go
func BenchmarkBookingService(b *testing.B) {
    service := setupBenchmarkService(b)

    b.ResetTimer()  // Exclude setup time

    for i := 0; i < b.N; i++ {
        service.Book("u1", "m1", 2)
    }
}

// Run: go test -bench=. -benchmem
// Output:
// BenchmarkBookingService-8    10000   112445 ns/op   1024 B/op   5 allocs/op
```

- `10000`: iterations
- `112445 ns/op`: nanoseconds per operation
- `1024 B/op`: bytes allocated per operation
- `5 allocs/op`: allocations per operation

### Benchmark Variations

```go
func BenchmarkDifferentSeatCounts(b *testing.B) {
    seatCounts := []int{1, 10, 100, 1000}

    for _, count := range seatCounts {
        b.Run(fmt.Sprintf("seats=%d", count), func(b *testing.B) {
            service := setupBenchmarkService(b)

            b.ReportAllocs()  // Show allocation stats
            b.ResetTimer()

            for i := 0; i < b.N; i++ {
                service.Book("u1", "m1", count)
            }
        })
    }
}

// Output:
// BenchmarkDifferentSeatCounts/seats=1-8       ...
// BenchmarkDifferentSeatCounts/seats=10-8      ...
// BenchmarkDifferentSeatCounts/seats=100-8     ...
// BenchmarkDifferentSeatCounts/seats=1000-8    ...
```

### Profiling Benchmarks

```bash
# CPU profile
go test -bench=. -cpuprofile=cpu.prof
go tool pprof cpu.prof

# Memory profile
go test -bench=. -memprofile=mem.prof
go tool pprof mem.prof

# Allocations profile
go test -bench=. -allocprofile=alloc.prof
```

In pprof:
```
(pprof) top     # Top functions by CPU time
(pprof) list BookingService.Book  # See line-by-line breakdown
(pprof) web     # Generate graph (requires graphviz)
```

---

## Part 6: Fuzzing

Go 1.18+ includes native fuzzing for finding edge cases and crashes.

### Basic Fuzz Test

```go
func FuzzParseBookingRequest(f *testing.F) {
    // Seed corpus
    f.Add([]byte(`{"user_id": "u1", "movie_id": "m1"}`))
    f.Add([]byte(`{}`))
    f.Add([]byte(`invalid json`))

    f.Fuzz(func(t *testing.T, data []byte) {
        // Fuzz target: Go will generate random inputs
        var req BookingRequest
        err := json.Unmarshal(data, &req)

        // Must not panic, regardless of input
        _ = err

        // Or test that valid inputs are processed
        if err == nil {
            if req.UserID != "" && req.MovieID != "" {
                _ = bookingService.Book(req.UserID, req.MovieID, 1)
            }
        }
    })
}

// Run: go test -fuzz=FuzzParseBookingRequest -fuzztime=30s
```

### Corpus Management

Fuzzing maintains a corpus directory:

```
booking/
├── booking_test.go
└── testdata/
    └── fuzz/
        └── FuzzParseBookingRequest/
            ├── 1234567890  # Failing input
            └── 9876543210  # Another case
```

When fuzzing finds a crash, it saves the input. Next run, fuzzing re-tests those inputs.

### Real-World Fuzz Example

```go
func FuzzCinemaChecker(f *testing.F) {
    f.Add("c1", "m1")
    f.Add("", "")
    f.Add("c1", "m1")

    f.Fuzz(func(t *testing.T, cinemaID, movieID string) {
        // Don't crash on any input
        ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
        defer cancel()

        _, err := cinemaChecker.CheckAvailability(ctx, Cinema{
            ID:  cinemaID,
            URL: "http://localhost:9999",  // Non-existent server
        })

        // Must handle errors gracefully
        if err != nil {
            if !errors.Is(err, context.DeadlineExceeded) && !strings.Contains(err.Error(), "connection refused") {
                // Some unexpected error; fuzzing caught it
            }
        }
    })
}
```

---

## Part 7: Race Detector in Tests

### Enabling Race Detection

```bash
go test -race ./...
go test -race -count=1 ./...  # -count=1 disables test caching
```

### Race Detector Example

```go
func TestConcurrentBooking(t *testing.T) {
    service := NewBookingService()

    var wg sync.WaitGroup
    for i := 0; i < 100; i++ {
        wg.Add(1)
        go func(id int) {
            defer wg.Done()
            service.Book(fmt.Sprintf("u%d", id), "m1", 1)
        }(i)
    }

    wg.Wait()
}

// Run: go test -race
// Output: (if race detected)
// WARNING: DATA RACE
// Write at 0x00c0001a2340 by goroutine 8:
//   main.BookingService.Book()
// Previous read at 0x00c0001a2340 by goroutine 7:
//   main.BookingService.CheckAvailable()
```

---

## Part 8: Coverage Analysis

### Generating Coverage Reports

```bash
# Generate coverage file
go test -coverprofile=coverage.out ./...

# View coverage in browser
go tool cover -html=coverage.out

# See percent covered
go test -cover ./...

# Focus on specific package
go test -coverprofile=coverage.out ./booking
go tool cover -html=coverage.out
```

### Coverage Best Practices

```go
func TestBookingService(t *testing.T) {
    tests := []struct {
        name string
        userID string
        movieID string
        seats int
        wantErr bool
    }{
        // Cover both success and error paths
        {"valid", "u1", "m1", 2, false},
        {"no user", "", "m1", 2, true},
        {"no movie", "u1", "", 2, true},
        {"no seats", "u1", "m1", 0, true},
        {"too many seats", "u1", "m1", 10000, true},
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            // Every if/else branch should be tested
        })
    }
}
```

---

## Part 9: Test Doubles (Fakes vs Mocks)

### Fakes: Simple Working Implementations

```go
type FakePaymentService struct {
    charges map[string]float64
}

func (f *FakePaymentService) Charge(ctx context.Context, userID string, amount float64) (string, error) {
    f.charges[userID] = amount
    return fmt.Sprintf("tx-%d", time.Now().Unix()), nil
}

func (f *FakePaymentService) GetCharges(userID string) float64 {
    return f.charges[userID]
}

// Usage
func TestBookingWithFakePayment(t *testing.T) {
    fake := &FakePaymentService{charges: make(map[string]float64)}
    service := NewBookingService(fake)

    service.Book("u1", "m1", 2)

    if fake.GetCharges("u1") != 99.99 {
        t.Error("payment not recorded")
    }
}
```

### Mocks: Behavior Verification

```go
type MockPaymentService struct {
    callCount int
    lastUser  string
    lastAmount float64
}

func (m *MockPaymentService) Charge(ctx context.Context, userID string, amount float64) (string, error) {
    m.callCount++
    m.lastUser = userID
    m.lastAmount = amount
    return "tx-123", nil
}

func (m *MockPaymentService) AssertCalled(t *testing.T, expected int) {
    if m.callCount != expected {
        t.Errorf("Charge called %d times; want %d", m.callCount, expected)
    }
}

// Usage
func TestBookingCallsPayment(t *testing.T) {
    mock := &MockPaymentService{}
    service := NewBookingService(mock)

    service.Book("u1", "m1", 2)

    mock.AssertCalled(t, 1)
    if mock.lastUser != "u1" {
        t.Errorf("user = %q; want u1", mock.lastUser)
    }
}
```

**Preference**: Fakes > Mocks. Fakes are simpler, more readable, and better for integration testing. Only use mocks when verifying specific call sequences matters.

---

## Part 10: Production Test Code

Complete example: Testing a booking service with multiple test types.

```go
package booking

import (
    "bytes"
    "context"
    "encoding/json"
    "errors"
    "fmt"
    "net/http"
    "net/http/httptest"
    "strings"
    "testing"
)

// FakePaymentService for unit tests
type FakePaymentService struct {
    shouldFail bool
    charges    map[string]float64
}

func (f *FakePaymentService) Charge(ctx context.Context, userID string, amount float64) (string, error) {
    if f.shouldFail {
        return "", errors.New("payment failed")
    }
    f.charges[userID] = amount
    return fmt.Sprintf("tx-%s", userID), nil
}

// Table-driven unit test
func TestBookingService(t *testing.T) {
    tests := []struct {
        name            string
        userID          string
        movieID         string
        seats           int
        paymentFails    bool
        wantErr         bool
        wantErrContains string
    }{
        {
            name:     "valid booking",
            userID:   "u1",
            movieID:  "m1",
            seats:    2,
            wantErr:  false,
        },
        {
            name:            "invalid user",
            userID:          "",
            movieID:         "m1",
            seats:           2,
            wantErr:         true,
            wantErrContains: "user",
        },
        {
            name:            "payment fails",
            userID:          "u1",
            movieID:         "m1",
            seats:           2,
            paymentFails:    true,
            wantErr:         true,
            wantErrContains: "payment",
        },
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            fake := &FakePaymentService{
                shouldFail: tt.paymentFails,
                charges:    make(map[string]float64),
            }

            service := NewBookingService(fake)
            err := service.Book(context.Background(), tt.userID, tt.movieID, tt.seats)

            if tt.wantErr && err == nil {
                t.Fatalf("expected error, got nil")
            }
            if !tt.wantErr && err != nil {
                t.Fatalf("unexpected error: %v", err)
            }
            if tt.wantErr && tt.wantErrContains != "" {
                if !strings.Contains(err.Error(), tt.wantErrContains) {
                    t.Errorf("error = %v; want substring %q", err, tt.wantErrContains)
                }
            }
        })
    }
}

// HTTP handler test
func TestBookingHandler(t *testing.T) {
    fake := &FakePaymentService{charges: make(map[string]float64)}
    service := NewBookingService(fake)
    handler := NewBookingHandler(service)

    reqBody := map[string]interface{}{
        "user_id":  "u1",
        "movie_id": "m1",
        "seats":    2,
    }
    bodyBytes, _ := json.Marshal(reqBody)

    req := httptest.NewRequest(http.MethodPost, "/book", bytes.NewReader(bodyBytes))
    req.Header.Set("Content-Type", "application/json")

    w := httptest.NewRecorder()
    handler.ServeHTTP(w, req)

    if w.Code != http.StatusOK {
        t.Errorf("status = %d; want 200", w.Code)
    }

    var response map[string]string
    json.NewDecoder(w.Body).Decode(&response)
    if response["booking_id"] == "" {
        t.Error("booking_id is empty")
    }
}

// Benchmark
func BenchmarkBookingService(b *testing.B) {
    fake := &FakePaymentService{charges: make(map[string]float64)}
    service := NewBookingService(fake)

    b.ReportAllocs()
    b.ResetTimer()

    for i := 0; i < b.N; i++ {
        service.Book(context.Background(), "u1", "m1", 2)
    }
}

// Fuzz test
func FuzzBooking(f *testing.F) {
    f.Add("u1", "m1", 1)
    f.Add("", "", 0)
    f.Add("user", "movie", 1000)

    f.Fuzz(func(t *testing.T, userID, movieID string, seats int) {
        fake := &FakePaymentService{charges: make(map[string]float64)}
        service := NewBookingService(fake)

        // Must not panic
        _ = service.Book(context.Background(), userID, movieID, seats)
    })
}
```

---

## Part 10: Test Binary Compilation and Custom Test Runners

You can compile tests into a standalone binary for CI/CD and custom execution:

```bash
# Compile test binary
go test -c -o test.binary ./...

# Run with custom flags
./test.binary -test.run "TestBooking" -test.v -test.count=3

# Run with filters
./test.binary -test.run "TestBooking/valid" -test.short

# Generate coverage without running all tests
./test.binary -test.coverprofile=coverage.out -test.run "TestFast"
```

This is useful for:
- CI/CD pipelines (build once, test many times)
- Performance testing (compile once, benchmark repeatedly)
- Custom test runners that need programmatic control

```go
// Custom test runner in Go
func main() {
    // Programmatically run tests from compiled binary
    // (This is rare; usually shell does this)

    // More common: use go test flags
}

// Better approach: use testing directly
func BenchmarkAllVariants(b *testing.B) {
    variants := []struct{ name string; setup func() }{
        {"v1", setupV1},
        {"v2", setupV2},
    }

    for _, v := range variants {
        v := v
        b.Run(v.name, func(b *testing.B) {
            impl := v.setup()
            b.ResetTimer()
            for i := 0; i < b.N; i++ {
                impl.Operation()
            }
        })
    }
}
```

---

## Part 11: Testing.Short() and Test Categorization

Go allows categorizing tests and running only specific categories:

```go
func TestQuickValidation(t *testing.T) {
    // Always run
    if true {
        t.Log("Fast test")
    }
}

func TestSlowDatabaseOperation(t *testing.T) {
    if testing.Short() {
        t.Skip("Skipping slow test in short mode")
    }

    // Database test takes 10 seconds
    time.Sleep(10 * time.Second)
}

// Run all tests
go test ./...

// Run only fast tests (for CI, quick feedback)
go test -short ./...
```

**Use case**: During development, run only fast tests with `-short`. Before commit, run all tests.

---

## Part 12: Parallel Tests and Subtests

```go
// Enable parallel test execution
func TestParallel(t *testing.T) {
    t.Parallel()  // Run this test in parallel with others

    // Safe because each test has isolated state
    for i := 0; i < 1000; i++ {
        go func(n int) {
            // Test something
        }(i)
    }
}

// Parallel subtests
func TestParallelSubtests(t *testing.T) {
    tests := []struct {
        name string
    }{
        {"test1"},
        {"test2"},
        {"test3"},
    }

    for _, tt := range tests {
        tt := tt  // Important: capture loop variable
        t.Run(tt.name, func(t *testing.T) {
            t.Parallel()  // Each subtest runs in parallel

            // Test logic
        })
    }
}

// Benchmark parallel performance
func BenchmarkParallel(b *testing.B) {
    b.RunParallel(func(pb *testing.PB) {
        for pb.Next() {
            expensiveOperation()
        }
    })
}
```

---

## Part 13: Snapshot Testing and Golden Files

```go
// Snapshot testing: verify output matches golden file
func TestBookingResponse(t *testing.T) {
    booking := Booking{
        ID:    "b123",
        UserID: "u456",
        Status: "confirmed",
    }

    response, _ := json.MarshalIndent(booking, "", "  ")

    // Read golden file
    golden, _ := os.ReadFile("testdata/booking_response.golden")

    // Update flag: go test -update
    // First time: creates golden file
    // Subsequent: compares against golden
    if string(response) != string(golden) {
        t.Errorf("response mismatch:\ngot:\n%s\nwant:\n%s", response, golden)

        // To update golden, run: go test -update
    }
}

// To use update pattern:
var update = flag.Bool("update", false, "update golden files")

func TestWithUpdate(t *testing.T) {
    result := doSomething()

    golden, _ := os.ReadFile("testdata/golden.txt")

    if *update {
        os.WriteFile("testdata/golden.txt", result, 0644)
    }

    if !bytes.Equal(result, golden) {
        t.Errorf("mismatch")
    }
}
```

---

## Part 14: Test Binary and Custom Test Runners

```go
// TestMain allows custom test setup/teardown
func TestMain(m *testing.M) {
    // Setup
    fmt.Println("Setting up tests...")
    setupGlobalResources()

    // Run all tests
    code := m.Run()

    // Teardown
    fmt.Println("Tearing down tests...")
    cleanupGlobalResources()

    // Exit with test result code
    os.Exit(code)
}

// Build test binary for custom use
// go test -c -o test.binary ./...
// ./test.binary -test.run TestName -test.v

// Run subset of tests programmatically
// ./test.binary -test.run "TestBooking.*" -test.v
```

---

## Interview Corner

### Q1: What is the table-driven test pattern and why is it Go standard?

**Model Answer**:
Table-driven tests organize multiple test cases as a slice of structs, each containing inputs and expected outputs. Each case runs in a subtest (via t.Run).

Advantages:
- Easy to add new test cases
- All cases visible in one place
- Subtests show up separately in output (-v)
- Reduces code duplication

```go
tests := []struct {
    name string
    input int
    want int
}{
    {"case1", 1, 2},
    {"case2", 2, 3},
}

for _, tt := range tests {
    t.Run(tt.name, func(t *testing.T) {
        // test logic
    })
}
```

### Q2: When should you use mocks vs fakes?

**Model Answer**:
- **Fakes**: Simple working implementations. Use by default. Better for integration tests.
- **Mocks**: Verify specific call sequences. Use only when call verification is critical.

Fakes are simpler and more maintainable. Mocks can be fragile (tests break if implementation details change).

Example: Use fake database for most tests. Use mock for verifying that an email is sent exactly once.

### Q3: What's the difference between b.ResetTimer and b.StopTimer?

**Model Answer**:
- **b.ResetTimer()**: Zero out elapsed time and allocation counters. Use after setup to exclude setup time from measurement.
- **b.StopTimer()/b.StartTimer()**: Pause/resume timing. Use when benchmark has intermixed setup that shouldn't be timed.

```go
func BenchmarkDB(b *testing.B) {
    db := setupDB()  // Not timed
    b.ResetTimer()   // Zero timer
    for i := 0; i < b.N; i++ {
        db.Query()  // Timed
    }
}
```

### Q4: How do you test concurrent code?

**Model Answer**:
1. Use `-race` flag: `go test -race ./...`
2. Spawn multiple goroutines, verify no data races
3. Use table-driven tests with concurrent variations
4. Test with high concurrency (1000+ goroutines) to find edge cases

```go
func TestConcurrentUpdate(t *testing.T) {
    counter := NewCounter()
    var wg sync.WaitGroup

    for i := 0; i < 1000; i++ {
        wg.Add(1)
        go func() {
            defer wg.Done()
            counter.Increment()
        }()
    }

    wg.Wait()
    if counter.Value() != 1000 {
        t.Errorf("counter = %d; want 1000", counter.Value())
    }
}

// Run: go test -race
```

### Q5: Design a test strategy for a payment API.

**Model Answer**:
1. **Unit tests**: Mock external services, test business logic
2. **Integration tests**: Real database, real external service mocks (httptest)
3. **Contract tests**: Verify API responses match expected schema
4. **Benchmarks**: Performance-critical paths (payment processing)
5. **Fuzz tests**: Random payment amounts, currencies, invalid inputs
6. **Load tests**: 1000 concurrent payments

```go
// Unit: Mock payment processor
// Integration: Real DB, fake stripe API
// Fuzz: Random amounts, currencies
// Benchmark: Payment latency
```

### Q6: How do you use testing.Short() effectively in a large test suite?

**Model Answer**:
Categorize tests by speed. Fast tests (unit) always run. Slow tests (integration, database) skip in short mode.

```go
func TestUnitValidation(t *testing.T) {
    // Always runs (< 1ms)
}

func TestIntegrationDatabase(t *testing.T) {
    if testing.Short() {
        t.Skip("slow integration test")
    }
    // Runs only with go test -short=false
}

// Workflow:
// 1. Write code, run: go test -short ./...  (fast feedback, 2-5 seconds)
// 2. Before commit: go test ./... (full suite, might take minutes)
// 3. CI: Full suite always
```

### Q7: What's the difference between benchmark memory analysis (-benchmem) and profiling?

**Model Answer**:
- **-benchmem**: Shows allocations per operation (B/op and allocs/op). Quick, lightweight.
  ```
  BenchmarkCache-8    10000000   100 ns/op   32 B/op   1 allocs/op
  ```
- **-cpuprofile/memprofile**: Detailed profiling (pprof). Shows which functions allocate.
  ```
  go test -cpuprofile=cpu.prof -bench=.
  go tool pprof cpu.prof
  (pprof) top  # Top CPU functions
  ```

Use -benchmem first to spot allocation hotspots. Use profiling to dig deeper.

### Q8: Design a comprehensive test suite for a concurrent cache with TTL.

**Model Answer**:
```go
func TestTTLCacheBasics(t *testing.T) {
    // Unit test: Set and Get
    cache := NewTTLCache[string, int](100 * time.Millisecond)
    cache.Set("key1", 42)

    if val, ok := cache.Get("key1"); !ok || val != 42 {
        t.Errorf("Set/Get failed")
    }
}

func TestTTLCacheExpiration(t *testing.T) {
    // Integration test: Expiration
    cache := NewTTLCache[string, int](100 * time.Millisecond)
    cache.Set("key1", 42)

    time.Sleep(150 * time.Millisecond)

    if _, ok := cache.Get("key1"); ok {
        t.Errorf("Value should be expired")
    }
}

func TestTTLCacheConcurrent(t *testing.T) {
    // Concurrent test with race detector
    cache := NewTTLCache[string, int](10 * time.Second)
    var wg sync.WaitGroup

    // 100 concurrent writers
    for i := 0; i < 100; i++ {
        wg.Add(1)
        go func(n int) {
            defer wg.Done()
            for j := 0; j < 100; j++ {
                key := fmt.Sprintf("key%d", n*100+j)
                cache.Set(key, j)
            }
        }(i)
    }

    // 100 concurrent readers
    for i := 0; i < 100; i++ {
        wg.Add(1)
        go func(n int) {
            defer wg.Done()
            for j := 0; j < 100; j++ {
                key := fmt.Sprintf("key%d", j)
                _, _ = cache.Get(key)
            }
        }(i)
    }

    wg.Wait()
    // Run with: go test -race
}

func BenchmarkTTLCacheGet(b *testing.B) {
    cache := NewTTLCache[string, int](10 * time.Second)
    cache.Set("key", 42)

    b.ReportAllocs()
    b.ResetTimer()

    for i := 0; i < b.N; i++ {
        cache.Get("key")
    }
}

func BenchmarkTTLCacheGetConcurrent(b *testing.B) {
    cache := NewTTLCache[string, int](10 * time.Second)
    cache.Set("key", 42)

    b.ReportAllocs()
    b.RunParallel(func(pb *testing.PB) {
        for pb.Next() {
            cache.Get("key")
        }
    })
}

func FuzzTTLCache(f *testing.F) {
    f.Add("key1", 42)
    f.Add("", 0)
    f.Add("very long key name with special chars", -1)

    f.Fuzz(func(t *testing.T, key string, value int) {
        cache := NewTTLCache[string, int](100 * time.Millisecond)

        // Must not crash
        cache.Set(key, value)
        _, _ = cache.Get(key)
        cache.Set(key, value)  // Overwrite
        _, _ = cache.Get(key)
    })
}
```

Test strategy:
- Unit: Basic set/get
- Integration: TTL expiration
- Concurrent: Race detector with high concurrency
- Benchmark: Single and parallel performance
- Fuzz: Robustness with random inputs

### Q9: How would you test error handling and edge cases in HTTP middleware?

**Model Answer**:
```go
func TestLoggingMiddlewareWithError(t *testing.T) {
    // Capture log output
    var logBuf bytes.Buffer
    logger := slog.New(slog.NewTextHandler(&logBuf, nil))

    handler := loggingMiddleware(logger)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        http.Error(w, "Internal error", http.StatusInternalServerError)
    }))

    req := httptest.NewRequest(http.MethodPost, "/test", nil)
    w := httptest.NewRecorder()

    handler.ServeHTTP(w, req)

    if w.Code != http.StatusInternalServerError {
        t.Errorf("status = %d; want 500", w.Code)
    }

    if !strings.Contains(logBuf.String(), "POST") {
        t.Errorf("log missing method")
    }
}

func TestRecoveryMiddlewarePanic(t *testing.T) {
    handler := recoveryMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        panic("intentional panic")
    }))

    req := httptest.NewRequest(http.MethodGet, "/test", nil)
    w := httptest.NewRecorder()

    // Must not panic
    handler.ServeHTTP(w, req)

    if w.Code != http.StatusInternalServerError {
        t.Errorf("recovery middleware should return 500")
    }
}

func TestTimeoutMiddleware(t *testing.T) {
    handler := timeoutMiddleware(1 * time.Second)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        select {
        case <-r.Context().Done():
            http.Error(w, "Timeout", http.StatusGatewayTimeout)
        case <-time.After(2 * time.Second):
            w.WriteHeader(http.StatusOK)
        }
    }))

    req := httptest.NewRequest(http.MethodGet, "/test", nil)
    w := httptest.NewRecorder()

    handler.ServeHTTP(w, req)

    if w.Code != http.StatusGatewayTimeout {
        t.Errorf("timeout not triggered")
    }
}
```

**Model Answer**:
- **-benchmem**: Shows allocations per operation (B/op and allocs/op). Quick, lightweight.
  ```
  BenchmarkCache-8    10000000   100 ns/op   32 B/op   1 allocs/op
  ```
- **-cpuprofile/memprofile**: Detailed profiling (pprof). Shows which functions allocate.
  ```
  go test -cpuprofile=cpu.prof -bench=.
  go tool pprof cpu.prof
  (pprof) top  # Top CPU functions
  ```

Use -benchmem first to spot allocation hotspots. Use profiling to dig deeper.

---

## Part 15: Integration Testing with Testcontainers and Transactions

```go
func TestBookingIntegration(t *testing.T) {
    ctx := context.Background()

    // Start PostgreSQL container
    req := testcontainers.ContainerRequest{
        Image:        "postgres:16-alpine",
        ExposedPorts: []string{"5432/tcp"},
        Env: map[string]string{
            "POSTGRES_USER":     "test",
            "POSTGRES_PASSWORD": "test",
            "POSTGRES_DB":       "testdb",
        },
        WaitingFor: wait.ForLog("database system is ready to accept connections"),
    }

    container, err := testcontainers.GenericContainer(ctx, testcontainers.GenericContainerRequest{
        ContainerRequest: req,
        Started:          true,
    })
    if err != nil {
        t.Fatal(err)
    }
    defer container.Terminate(ctx)

    // Get connection details
    host, _ := container.Host(ctx)
    port, _ := container.MappedPort(ctx, "5432/tcp")
    connString := fmt.Sprintf("postgres://test:test@%s:%s/testdb?sslmode=disable",
        host, port.Port())

    // Connect and migrate
    db, _ := pgx.Connect(ctx, connString)
    defer db.Close(ctx)

    // Run migrations
    _, _ = db.Exec(ctx, `
        CREATE TABLE bookings (
            id SERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            movie_id TEXT NOT NULL,
            status TEXT NOT NULL
        )
    `)

    // Test with transaction rollback
    testCases := []struct {
        name   string
        testFn func(*testing.T, *pgx.Pool)
    }{
        {
            "create booking",
            func(t *testing.T, pool *pgx.Pool) {
                tx, _ := pool.Begin(ctx)
                defer tx.Rollback(ctx)

                var id int
                _ = tx.QueryRow(ctx,
                    "INSERT INTO bookings (user_id, movie_id, status) VALUES ($1, $2, $3) RETURNING id",
                    "u1", "m1", "confirmed").Scan(&id)

                if id == 0 {
                    t.Error("booking not created")
                }
            },
        },
    }

    for _, tc := range testCases {
        t.Run(tc.name, func(t *testing.T) {
            tc.testFn(t, db)
        })
    }
}
```

Benefits:
- Real database (PostgreSQL, MySQL, Redis, etc. via Docker)
- Transaction isolation (each test rolls back)
- Mirrors production environment
- Tests actual query execution

---

## Tradeoffs and Best Practices

### Test Coverage
- Aim for 70-80% coverage
- 100% coverage ≠ bug-free code
- Focus on critical paths and error handling

### Test Speed
- Unit tests: <1s
- Integration tests: <10s
- Slow tests discourage running them frequently
- Use `-count=1` to disable caching during development

### Mocks and Dependencies
- Prefer dependency injection over global state
- Use interfaces for mockable dependencies
- Keep mocks simple (fakes better than mocks)

### Benchmark Rigor
- Run benchmarks multiple times: `go test -bench=. -count=5`
- Compare before/after changes
- Be aware of CPU throttling and OS noise

---

## Exercise

Build comprehensive tests for a **movie booking service**:

1. **Unit tests** (table-driven): Book validation, seat availability checks
2. **HTTP tests** (httptest): POST /book, GET /bookings endpoints
3. **Integration tests** (real database): Booking persistence, transaction isolation
4. **Benchmarks**: Book operation latency, database query performance
5. **Concurrent tests** (-race): 100 concurrent bookings, verify no races
6. **Fuzz tests**: Invalid requests, malformed JSON

Requirements:
- Must pass `go test -race`
- Must have >80% coverage
- Must include both happy path and error cases
- Must use table-driven tests
- Must benchmark critical paths

Bonus: Add testcontainers for real PostgreSQL, test transaction rollback on failure.

