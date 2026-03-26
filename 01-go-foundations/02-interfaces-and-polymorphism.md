# Interfaces and Polymorphism: Go's Most Powerful Design Pattern

## The Problem

Coming from TypeScript and React Native, you expect inheritance hierarchies: `class PaymentGateway { charge() }` with `StripeGateway extends PaymentGateway`. Go has none of this. Instead, Go has **implicit interface satisfaction**.

This is Go's most radical design choice: if your type has the right methods, it automatically satisfies the interface. No explicit declaration needed. This sounds chaotic but it's the foundation of Go's entire ecosystem.

At senior levels, you must:
- Understand the `interface{}` / `any` type and when it's appropriate
- Design interfaces for dependency injection (not framework magic)
- Know the io.Reader/Writer ecosystem (used everywhere)
- Understand interface values and nil semantics
- Mock interfaces for testing without code generation
- Avoid interface pollution and over-abstraction
- Design "Accept interfaces, return structs"

This lesson is about making Go's implicit, composition-first design work for you.

## Theory: Interface Fundamentals

### Implicit Satisfaction is Go's Superpower and Its Design Philosophy

In Go, you never write `implements`. This single decision—to make interface satisfaction implicit—shapes the entire language's architecture.

```go
type PaymentGateway interface {
	Charge(ctx context.Context, amount int) error
	Refund(ctx context.Context, transactionID string) error
}

type StripeGateway struct {
	apiKey string
}

// No "implements PaymentGateway" declaration needed
func (sg *StripeGateway) Charge(ctx context.Context, amount int) error {
	// implementation
	return nil
}

func (sg *StripeGateway) Refund(ctx context.Context, transactionID string) error {
	// implementation
	return nil
}

// StripeGateway now satisfies PaymentGateway automatically
```

Why does this matter? This is a fundamental shift in how you design systems:

1. **Decoupling**: The interface and the implementation don't need to know about each other. Interface lives in domain logic, implementation lives in persistence layer. Neither imports the other.
2. **Retrofitting**: You can wrap a third-party library with an interface without modifying it. SQLite, PostgreSQL, MySQL—all become `database.Queryer` without any declaration.
3. **Small interfaces**: Encourages single-responsibility interfaces instead of god interfaces. The io.Reader interface (one method!) powers the entire ecosystem because it's small.
4. **Testability**: Mock implementations can be defined anywhere, even in test files. No separate test framework, no code generation—just implement the interface.
5. **Backward compatibility**: Adding methods to an interface breaks all implementations, but only if they need those methods. In implicit satisfaction, you're free to return new types that satisfy old interfaces.

Compare to TypeScript's explicit inheritance:

```typescript
// TypeScript requires explicit declaration
interface PaymentGateway {
  charge(amount: number): Promise<void>;
  refund(transactionID: string): Promise<void>;
}

class StripeGateway implements PaymentGateway {
  async charge(amount: number): Promise<void> {
    // Must declare implements
  }
  async refund(transactionID: string): Promise<void> {
    // Must implement every interface method
  }
}

// If you add a method to PaymentGateway, StripeGateway breaks
// If StripeGateway doesn't explicitly implement, TypeScript errors
```

Go's approach:

```go
// PaymentGateway defined in payment package
type PaymentGateway interface {
	Charge(ctx context.Context, amount int) error
	Refund(ctx context.Context, txID string) error
}

// StripeGateway in stripe subpackage - no mention of PaymentGateway
type StripeGateway struct { apiKey string }

func (s *StripeGateway) Charge(ctx context.Context, amount int) error { ... }
func (s *StripeGateway) Refund(ctx context.Context, txID string) error { ... }

// StripeGateway automatically satisfies PaymentGateway
// No imports, no declarations, no coupling between stripe and payment packages
```

Go's approach means you **discover interfaces after you've written implementations**. This shifts the design philosophy: **start with concrete types, extract interfaces when you see multiple implementations**. This is the opposite of interface-first design (common in Java) and leads to better, simpler abstractions.

Real-world example from the Go standard library:

```go
// io package defines
type Reader interface {
	Read(p []byte) (n int, err error)
}

// os package implements without knowing about io.Reader
type File struct { /* ... */ }
func (f *File) Read(p []byte) (n int, err error) { /* ... */ }

// bytes package implements
type Buffer struct { /* ... */ }
func (b *Buffer) Read(p []byte) (n int, err error) { /* ... */ }

// gzip package implements
type Reader struct { /* ... */ }
func (r *Reader) Read(p []byte) (n int, err error) { /* ... */ }

// json package implements
type Decoder struct { /* ... */ }
func (d *Decoder) Read(p []byte) (n int, err error) { ... } // (actually Decode, but you get the point)

// All these implementations were written at different times by different teams
// No one needed to know about io.Reader when implementing
// Yet they're all composable
```

This is why Rob Pike says "the interface segregation principle is implicit in Go" and why interfaces are Go's greatest strength.

### The interface{} / any Type

`interface{}` is Go's universal type. It matches any value because an empty interface has no methods—everything satisfies it:

```go
var x any = "hello"      // string
var y any = 42           // int
var z any = []int{1, 2}  // slice
var w any = Movie{...}   // struct

// You can store anything, but you lose type information
```

**When to use `any`**:
- JSON unmarshaling: don't know the structure ahead of time
- Printf format strings: `fmt.Printf("%v", x)` works with any type
- Database query results: columns can be different types
- Reflection: when you need to inspect types at runtime

**When to avoid `any`**:
- Function parameters: use a real interface or type parameter (generics)
- Return values: expose the actual type so callers know what they have
- Storing multiple types in a single slice: use a tagged union or distinct type instead

```go
// BAD: loses type information
func Process(data any) {
	// Now I have to figure out what data actually is
	switch v := data.(type) {
	case string:
		// process string
	case int:
		// process int
	default:
		panic("unknown type")
	}
}

// GOOD: explicit about what you accept
func Process(s string) {
	// Now I know it's a string
}
```

**interface{} vs typed interfaces**:

```go
// interface{}: flexible but unsafe
func WriteData(db any, data any) error {
	// Could be a SQL database, could be a file, could be nil
	// Type assertion required at runtime
}

// Typed interface: flexible and safe
type Database interface {
	Write(ctx context.Context, data any) error
}

func WriteData(db Database, data any) error {
	// db is known to implement Write
	return db.Write(context.Background(), data)
}
```

### Interface Values: The (Type, Value) Pair and Layout

An interface value in Go is internally a pair: (type, value). When you assign a value to an interface, Go stores both. The runtime can then dispatch method calls to the correct implementation based on the stored type.

```go
var g PaymentGateway
g = &StripeGateway{apiKey: "sk_live_..."}

// Under the hood (internal representation):
// g = (type: *StripeGateway, value: 0xc000abc123)
//     (a pointer to runtime type info, a pointer to the actual StripeGateway struct)
```

The layout on a 64-bit system is 16 bytes:

```
Interface Value Layout:
┌──────────────────────┬──────────────────────┐
│  Type Descriptor (8b)│  Data Pointer (8b)   │
└──────────────────────┴──────────────────────┘
  (pointer to *StripeGateway    (pointer to actual struct)
   type metadata)              at 0xc000abc123
```

When a method is called on an interface, the runtime:
1. Looks up the method in the type descriptor
2. Calls the function with the data pointer as the receiver

This is why method dispatch on interfaces is fast (one pointer dereference) but not free.

**nil interfaces vs interfaces holding nil**: This is the most confusing aspect of Go interfaces:

```go
var g PaymentGateway     // (nil, nil) - both type and value are nil
g == nil                 // true

var stripe *StripeGateway = nil  // nil pointer, but not nil when assigned
g = stripe               // (type: *StripeGateway, value: nil)
g == nil                 // FALSE! Type field is not nil
```

The comparison `g == nil` checks if BOTH type and value are nil. If either is non-nil, the interface is not nil.

This is a classic gotcha:

```go
func CreateGateway(useFake bool) PaymentGateway {
	if useFake {
		var f *FakeGateway  // This is nil
		return f            // Returns (type: *FakeGateway, value: nil)
	}
	return &RealGateway{}
}

func main() {
	g := CreateGateway(true)
	if g == nil {
		fmt.Println("Gateway is nil")  // Never prints!
	}
	// g is not nil (type is non-nil), so your nil checks fail
	// Calling g.Charge() will panic with "nil pointer dereference"
}
```

Solution 1: Check the underlying value:

```go
func checkPaymentGateway(g PaymentGateway) {
	if g == nil || reflect.ValueOf(g).IsNil() {
		fmt.Println("gateway is nil or holds nil")
		return
	}
}
```

(Using reflect is slow, but correct)

Solution 2: Return concrete types and only use interfaces at boundaries:

```go
// Return concrete type from constructor
func CreateGateway(useFake bool) *StripeGateway {
	if useFake {
		return nil  // This is a true nil
	}
	return &StripeGateway{}
}

func main() {
	g := CreateGateway(true)
	if g == nil {
		fmt.Println("Gateway is nil")  // Prints correctly
	}
}

// Accept interfaces, return concrete types
func CreateBookingService(g PaymentGateway) *BookingService {
	// Service holds the interface (which could be nil or hold nil)
	return &BookingService{gateway: g}
}
```

Solution 3 (Best): Design APIs so this can't happen:

```go
// Don't return nil from constructors; return an error
func NewStripeGateway(key string) (*StripeGateway, error) {
	if key == "" {
		return nil, fmt.Errorf("api key required")
	}
	return &StripeGateway{apiKey: key}, nil
}

// Caller must handle error explicitly
g, err := NewStripeGateway(key)
if err != nil {
	return err  // Can't accidentally get nil interface holding nil
}
```

**Performance of interface dispatch**: Calling a method on an interface has a small but measurable cost:

```go
// Benchmark: method call on concrete type vs interface
type Counter interface {
	Increment()
}

type SimpleCounter struct {
	count int
}

func (c *SimpleCounter) Increment() {
	c.count++
}

// Direct call
func BenchmarkDirect(b *testing.B) {
	c := &SimpleCounter{}
	for i := 0; i < b.N; i++ {
		c.Increment()
	}
}
// Result: ~1 ns/op

// Interface call
func BenchmarkInterface(b *testing.B) {
	var c Counter = &SimpleCounter{}
	for i := 0; i < b.N; i++ {
		c.Increment()
	}
}
// Result: ~5 ns/op (5x slower)
```

The ~4ns cost is the type lookup and method dispatch. In hot loops, this matters. But for most code, it's negligible.

### Interface Embedding and Composition

Interfaces can embed other interfaces:

```go
type Reader interface {
	Read(p []byte) (n int, err error)
}

type Writer interface {
	Write(p []byte) (n int, err error)
}

type ReadWriter interface {
	Reader
	Writer
}

// Now ReadWriter requires both Read and Write methods
```

Interfaces can also embed other interfaces, creating larger abstractions:

```go
type Database interface {
	Query(ctx context.Context, sql string, args ...any) (Rows, error)
	Exec(ctx context.Context, sql string, args ...any) (Result, error)
}

type Transaction interface {
	Database  // Embed all Database methods
	Commit(ctx context.Context) error
	Rollback(ctx context.Context) error
}
```

A type satisfying `Transaction` must implement all four methods (Query, Exec, Commit, Rollback).

This allows incremental interface growth without breaking existing code. A new interface can extend an old one without modifying it.

**Practical design pattern for databases**:

```go
// Basic operations, used by most code
type Querier interface {
	Query(ctx context.Context, sql string, args ...any) (Rows, error)
}

type Executor interface {
	Exec(ctx context.Context, sql string, args ...any) (Result, error)
}

// Transactions combine them
type Transactor interface {
	BeginTx(ctx context.Context, opts TxOptions) (Tx, error)
}

// A full DB connection
type Database interface {
	Querier
	Executor
	Transactor
}

// Usage: functions accept only what they need
func FetchMovies(ctx context.Context, q Querier) ([]Movie, error) {
	// Can't accidentally use Exec or BeginTx; compile error
}

func SaveUser(ctx context.Context, e Executor, user *User) error {
	// Only has Exec
}

func WithTx(ctx context.Context, db Database, fn func(Tx) error) error {
	// Has all three
}

// Testing: mock only the interface you need
type MockQuerier struct{}
func (m *MockQuerier) Query(ctx context.Context, sql string, args ...any) (Rows, error) {
	// Return test data
}

// In tests, use it anywhere a Querier is expected
```

This is why Go's interfaces are so powerful: you can express "this function needs JUST Query capability" and guarantee it can't use Exec. No other language makes this so easy.

### The io.Reader / io.Writer Ecosystem: The Foundation of Composition

The most important interfaces in Go are deceptively simple:

```go
type Reader interface {
	Read(p []byte) (n int, err error)
}

type Writer interface {
	Write(p []byte) (n int, err error)
}

type Closer interface {
	Close() error
}

type ReadCloser interface {
	Reader
	Closer
}

type ReadWriter interface {
	Reader
	Writer
}
```

These four simple interfaces (one, two, three methods respectively) power the entire Go ecosystem. They're the foundation of composition.

**Understanding io.Reader**: The interface says "read up to len(p) bytes into p and return how many you actually read". This is brilliantly simple:

```go
// *os.File implements Reader
f, _ := os.Open("file.txt")
buf := make([]byte, 4096)
n, err := f.Read(buf)
// Read at most 4096 bytes, get back how many were actually read
// If EOF, err == io.EOF

// *gzip.Reader implements Reader
gz, _ := gzip.NewReader(f)
n, err := gz.Read(buf)  // Read compressed data, get back decompressed

// *bytes.Buffer implements Reader
b := bytes.NewBufferString("hello")
n, err := b.Read(buf)  // Read from memory

// *http.Response.Body implements Reader
resp, _ := http.Get("https://api.example.com/data")
n, err := resp.Body.Read(buf)  // Read response body

// All four can be used interchangeably
```

**The power of composition**: You can chain readers without knowing their implementation:

```go
// Read gzip-compressed data from HTTP response
resp, _ := http.Get("https://example.com/data.gz")
defer resp.Body.Close()

gz, _ := gzip.NewReader(resp.Body)
defer gz.Close()

// Decompress and save to file
outFile, _ := os.Create("data.json")
defer outFile.Close()

io.Copy(outFile, gz)  // Works seamlessly across three different Reader types
```

**Building wrapper readers**: You can extend any Reader with additional behavior:

```go
// Rate-limiting reader (throttles throughput)
type RateLimitedReader struct {
	r io.Reader
	limiter *rate.Limiter
}

func (rlr *RateLimitedReader) Read(p []byte) (int, error) {
	// Wait for rate limiter before each read
	if err := rlr.limiter.Wait(context.Background()); err != nil {
		return 0, err
	}
	return rlr.r.Read(p)
}

// Logging reader (logs all reads)
type LoggingReader struct {
	r io.Reader
	logger *log.Logger
}

func (lr *LoggingReader) Read(p []byte) (int, error) {
	n, err := lr.r.Read(p)
	lr.logger.Printf("read %d bytes: %v\n", n, err)
	return n, err
}

// Compose multiple wrappers
reader := &RateLimitedReader{
	r: &LoggingReader{
		r: os.Stdin,
		logger: log.New(os.Stderr, "", 0),
	},
	limiter: rate.NewLimiter(rate.Every(time.Millisecond), 1),
}

// Read from stdin, with logging and rate limiting
io.Copy(os.Stdout, reader)
```

**Why this matters**: The io.Reader interface is so successful because:
1. It's minimal (one method) - easy to implement
2. It's universal (everything that produces bytes implements it)
3. It's composable (readers wrap readers wrap readers)
4. It's powerful (works with files, network, compression, memory, pipes, etc.)

The Go philosophy is to find the minimal interfaces that solve real problems, then build on them. io.Reader is Exhibit A.

**Practical examples in a web service**:

```go
// Handler that accepts uploaded files
func UploadMovie(w http.ResponseWriter, r *http.Request) {
	file, _, err := r.FormFile("movie")
	if err != nil {
		w.WriteHeader(http.StatusBadRequest)
		return
	}
	defer file.Close()

	// file is io.ReadCloser; we can wrap it
	limiter := &RateLimitedReader{r: file, limiter: rate.NewLimiter(...)}
	hash := md5.NewWriter()

	// Copy the file to hash, limiting throughput
	io.Copy(hash, limiter)

	// Now we have the hash without loading the entire file in memory
	// And we limited bandwidth to prevent DoS
}
```

This is the power of small, focused interfaces.

### sort.Interface, fmt.Stringer, and error

The standard library defines a few key interfaces that become ad-hoc protocols:

```go
// sort.Interface: needed to sort a custom type
type Interface interface {
	Len() int
	Less(i, j int) bool
	Swap(i, j int)
}

// Example
type Movies []Movie

func (m Movies) Len() int           { return len(m) }
func (m Movies) Less(i, j int) bool { return m[i].Title < m[j].Title }
func (m Movies) Swap(i, j int)      { m[i], m[j] = m[j], m[i] }

sort.Sort(Movies{...})
```

The `error` interface is everywhere:

```go
type error interface {
	Error() string
}

// Any type with Error() satisfies error
type PaymentError struct {
	Code    string
	Message string
}

func (e PaymentError) Error() string {
	return fmt.Sprintf("%s: %s", e.Code, e.Message)
}

var err error = PaymentError{"DECLINED", "card declined"}
```

## Production Code: Payment Gateway Abstraction

Here's a realistic dependency injection pattern using interfaces:

```go
package payment

import (
	"context"
	"fmt"
	"sync"

	"github.com/jackc/pgx/v5"
)

// PaymentGateway defines the contract any payment processor must implement
type PaymentGateway interface {
	Charge(ctx context.Context, movieBookingID string, amountCents int) (*Transaction, error)
	Refund(ctx context.Context, transactionID string) (*Transaction, error)
	GetStatus(ctx context.Context, transactionID string) (*Transaction, error)
}

// Transaction represents a payment result
type Transaction struct {
	ID        string
	Status    string // "success", "declined", "pending"
	AmountCents int
	ProcessedAt string
	ErrorCode string
	ErrorMessage string
}

// StripeGateway implements PaymentGateway
type StripeGateway struct {
	apiKey string
	httpClient HTTPClient
}

type HTTPClient interface {
	Do(req *http.Request) (*http.Response, error)
}

func NewStripeGateway(apiKey string, client HTTPClient) *StripeGateway {
	return &StripeGateway{
		apiKey: apiKey,
		httpClient: client,
	}
}

func (sg *StripeGateway) Charge(ctx context.Context, bookingID string, amountCents int) (*Transaction, error) {
	// Stripe API call
	// Implement actual Stripe charging logic
	return &Transaction{
		ID: fmt.Sprintf("ch_stripe_%s", bookingID),
		Status: "success",
		AmountCents: amountCents,
	}, nil
}

func (sg *StripeGateway) Refund(ctx context.Context, transactionID string) (*Transaction, error) {
	return &Transaction{
		ID: fmt.Sprintf("ref_%s", transactionID),
		Status: "success",
	}, nil
}

func (sg *StripeGateway) GetStatus(ctx context.Context, transactionID string) (*Transaction, error) {
	return &Transaction{ID: transactionID, Status: "success"}, nil
}

// LocalPaymentGateway: for testing, uses in-memory storage
type LocalPaymentGateway struct {
	mu sync.Mutex
	transactions map[string]*Transaction
}

func NewLocalPaymentGateway() *LocalPaymentGateway {
	return &LocalPaymentGateway{
		transactions: make(map[string]*Transaction),
	}
}

func (lpg *LocalPaymentGateway) Charge(ctx context.Context, bookingID string, amountCents int) (*Transaction, error) {
	lpg.mu.Lock()
	defer lpg.mu.Unlock()

	txn := &Transaction{
		ID: fmt.Sprintf("local_%s", bookingID),
		Status: "success",
		AmountCents: amountCents,
	}
	lpg.transactions[txn.ID] = txn
	return txn, nil
}

func (lpg *LocalPaymentGateway) Refund(ctx context.Context, transactionID string) (*Transaction, error) {
	lpg.mu.Lock()
	defer lpg.mu.Unlock()

	txn, ok := lpg.transactions[transactionID]
	if !ok {
		return nil, fmt.Errorf("transaction not found: %s", transactionID)
	}
	txn.Status = "refunded"
	return txn, nil
}

func (lpg *LocalPaymentGateway) GetStatus(ctx context.Context, transactionID string) (*Transaction, error) {
	lpg.mu.Lock()
	defer lpg.mu.Unlock()

	txn, ok := lpg.transactions[transactionID]
	if !ok {
		return nil, fmt.Errorf("transaction not found: %s", transactionID)
	}
	return txn, nil
}

// BookingService uses PaymentGateway without knowing which implementation
type BookingService struct {
	db *pgx.Conn
	gateway PaymentGateway
}

func NewBookingService(db *pgx.Conn, gateway PaymentGateway) *BookingService {
	return &BookingService{
		db: db,
		gateway: gateway,
	}
}

func (bs *BookingService) CreateBooking(ctx context.Context, userID string, seats []string) (string, error) {
	// Calculate total price
	totalCents := len(seats) * 1500 // $15 per seat

	// Charge the payment gateway
	txn, err := bs.gateway.Charge(ctx, fmt.Sprintf("booking_%s", userID), totalCents)
	if err != nil {
		return "", fmt.Errorf("payment failed: %w", err)
	}

	if txn.Status != "success" {
		return "", fmt.Errorf("payment declined: %s", txn.ErrorMessage)
	}

	// Insert booking into database
	var bookingID string
	err = bs.db.QueryRow(ctx, `
		INSERT INTO bookings (user_id, seats, transaction_id, total_amount_cents)
		VALUES ($1, $2, $3, $4)
		RETURNING id
	`, userID, seats, txn.ID, totalCents).Scan(&bookingID)

	if err != nil {
		// Refund the charge if booking insert fails
		_, _ = bs.gateway.Refund(ctx, txn.ID)
		return "", fmt.Errorf("insert booking: %w", err)
	}

	return bookingID, nil
}

// Dependency injection in main()
func main() {
	conn, _ := pgx.Connect(context.Background(), "postgres://...")

	var gateway PaymentGateway

	if os.Getenv("ENV") == "test" {
		gateway = NewLocalPaymentGateway()
	} else {
		gateway = NewStripeGateway(os.Getenv("STRIPE_KEY"), http.DefaultClient)
	}

	service := NewBookingService(conn, gateway)
	// service uses either Stripe or LocalPaymentGateway without knowing which
}
```

**Key patterns**:
1. Interface is small (3 methods) and focused
2. Multiple implementations (Stripe, LocalPaymentGateway)
3. Dependency injection via constructor
4. Caller doesn't know which implementation is active
5. Easy to test: pass LocalPaymentGateway in tests

## Mock Patterns for Testing

You don't need code generation. Hand-written mocks are often better:

```go
// Mock implementation in _test.go
type MockPaymentGateway struct {
	ChargeFunc func(ctx context.Context, bookingID string, amountCents int) (*Transaction, error)
	RefundFunc func(ctx context.Context, transactionID string) (*Transaction, error)
	GetStatusFunc func(ctx context.Context, transactionID string) (*Transaction, error)

	ChargeCalls []struct {
		BookingID string
		AmountCents int
	}
	RefundCalls []struct {
		TransactionID string
	}
}

func (m *MockPaymentGateway) Charge(ctx context.Context, bookingID string, amountCents int) (*Transaction, error) {
	m.ChargeCalls = append(m.ChargeCalls, struct {
		BookingID string
		AmountCents int
	}{BookingID, AmountCents})

	if m.ChargeFunc != nil {
		return m.ChargeFunc(ctx, bookingID, amountCents)
	}
	return &Transaction{Status: "success"}, nil
}

func (m *MockPaymentGateway) Refund(ctx context.Context, transactionID string) (*Transaction, error) {
	m.RefundCalls = append(m.RefundCalls, struct {
		TransactionID string
	}{TransactionID})

	if m.RefundFunc != nil {
		return m.RefundFunc(ctx, transactionID)
	}
	return &Transaction{Status: "refunded"}, nil
}

// Usage in tests
func TestBookingWithDeclinedPayment(t *testing.T) {
	mock := &MockPaymentGateway{
		ChargeFunc: func(ctx context.Context, bookingID string, amountCents int) (*Transaction, error) {
			return &Transaction{
				Status: "declined",
				ErrorCode: "INSUFFICIENT_FUNDS",
			}, nil
		},
	}

	service := NewBookingService(nil, mock)
	_, err := service.CreateBooking(context.Background(), "user123", []string{"A1", "A2"})

	if err == nil {
		t.Fatal("expected error")
	}

	if len(mock.ChargeCalls) != 1 {
		t.Fatalf("expected 1 charge call, got %d", len(mock.ChargeCalls))
	}
}
```

## Accept Interfaces, Return Structs

This is Go's design philosophy:

```go
// GOOD: Accept interface, return concrete type
func NewMovieDB(conn *pgx.Conn) *MovieDB {
	return &MovieDB{conn: conn}
}

func FindMovieByTitle(searcher MovieSearcher, title string) (*Movie, error) {
	return searcher.SearchByTitle(context.Background(), title)
}

// Caller can inject any searcher, but gets a specific Movie back
```

Why?

1. **Input flexibility**: Callers can use any type that satisfies the interface
2. **Output clarity**: Callers know exactly what they're getting back
3. **API stability**: Adding methods to a concrete struct doesn't break callers

Contrast:

```go
// BAD: Return interface
func FindMovie() MovieSearcher {
	// What is this? Callers don't know what methods are available
}
```

## Interface Pollution and Over-Abstraction

**When interfaces become harmful**:

```go
// BAD: God interface
type Database interface {
	Query(ctx context.Context, sql string, args ...any) (Rows, error)
	Exec(ctx context.Context, sql string, args ...any) (Result, error)
	BeginTx(ctx context.Context, opts TxOptions) (Tx, error)
	GetConnection(ctx context.Context) (*Connection, error)
	SetMaxConnections(int) error
	SetConnMaxLifetime(time.Duration) error
	Stats() PoolStats
	// 20 more methods...
}
```

This interface is too big. It forces implementers to implement everything, and callers can't depend on just the parts they need.

**Better approach**: Small, focused interfaces

```go
type Querier interface {
	Query(ctx context.Context, sql string, args ...any) (Rows, error)
}

type Executor interface {
	Exec(ctx context.Context, sql string, args ...any) (Result, error)
}

type Transactor interface {
	BeginTx(ctx context.Context, opts TxOptions) (Tx, error)
}

// Compose them
type Database interface {
	Querier
	Executor
	Transactor
}

// But most functions only need one interface
func FetchUsers(ctx context.Context, q Querier) ([]User, error) {
	rows, err := q.Query(ctx, "SELECT * FROM users", nil)
	// ...
}
```

## Interview Corner: Common Questions and Answers

**Q1: Explain implicit interface satisfaction and why it matters.**

A: In Go, a type satisfies an interface if it implements all the interface's methods—no explicit declaration needed. This is Go's most distinctive feature. It's powerful because: (1) You can define an interface without importing the package of the implementation—they're completely decoupled; (2) Third-party types automatically satisfy your interfaces if they happen to have the right methods—no wrapper needed; (3) It encourages small, focused interfaces because you can't require explicit satisfaction; (4) You discover interfaces after writing implementations, leading to better designs. This is fundamentally different from explicit inheritance (`implements`) in TypeScript. It's also why Go's ecosystem is so composable—everyone writes Reader and Writer implementations without knowing about each other.

**Q2: What's the difference between `nil` and an interface holding `nil`?**

A: An interface value is a (type, value) pair. `var x interface{} = nil` is (nil, nil) and `x == nil` is true. But `var p *Foo = nil; x = p` creates (type: *Foo, value: nil), and `x == nil` is false. This is a common gotcha when checking if an interface is nil—you need `reflect.ValueOf(x).IsNil()` or check the concrete type.

**Q3: When should you use `interface{}` vs a concrete type vs a generic type parameter?**

A: Use `interface{}` only when you truly don't know the type (JSON unmarshaling, fmt.Printf). For most code, use a concrete type or a small, focused interface. Use generic type parameters (Go 1.18+) when you need to work with any type but still want type safety (`func Map[T any, U any](items []T) []U`).

**Q4: Explain the io.Reader interface and why it's important.**

A: `io.Reader` is a single-method interface: `Read(p []byte) (n int, err error)`. It's simple but powerful because every way to get bytes implements it: files, network sockets, gzip readers, buffers, pipes, etc. This allows you to write functions that work with any source of bytes without knowing the implementation. It's the foundation of Go's composition-based design.

**Q5: How would you design interfaces for a multi-tenant SaaS system?**

A: Start small: `type Repository interface { Get(ctx context.Context, id string) (T, error) }`. Separate read and write concerns: `type Reader interface { ... }`, `type Writer interface { ... }`. Create per-domain interfaces for movies, bookings, payments. Compose them in service types: `type BookingService struct { movieReader Reader, bookingWriter Writer }`. This keeps dependencies explicit and testable.

**Q6: You need to mock a `*sql.DB` in tests. Should you create an interface?**

A: Yes, but not a "database" interface. Create small, focused interfaces: `type Querier interface { Query(ctx context.Context, sql string, args ...any) (Rows, error) }`. This way, your code depends on Querier (which is small and easy to mock), not the entire *sql.DB. Then in tests, you can mock just the Query method.

**Q7: What's the "Accept interfaces, return structs" principle?**

A: Function parameters should accept interfaces (flexible), but return types should be concrete structs (clear). This gives callers the ability to inject different implementations (for testing, different backends) while guaranteeing they know what they're receiving. Example: `func FindMovie(searcher MovieSearcher, id string) (*Movie, error)` accepts any searcher but returns a specific *Movie.

**Q8: How do you handle interface composition vs over-abstraction?**

A: Embed small interfaces, not god interfaces. If a package has 30 methods, split it: `type Reader interface { Read(...) }`, `type Closer interface { Close(...) }`, then compose: `type ReadCloser interface { Reader; Closer }`. This lets callers depend on just what they need and allows mocking specific behaviors.

**Q9: You have a database that needs to support both PostgreSQL and MongoDB. How do you use interfaces to make this clean?**

A: Define an interface for each operation: `type MovieQuerier interface { GetMovieByID(ctx, id) (*Movie, error) }`, `type MovieWriter interface { SaveMovie(ctx, m) error }`. PostgreSQL and MongoDB each implement these independently. Your business logic depends only on the interfaces. To swap implementations, you just change which concrete type you construct in main(). The interfaces act as contracts that both implementations must satisfy.

**Q10: Why is io.Reader such a good interface?**

A: io.Reader is exactly one method: `Read(p []byte) (n int, err error)`. It's so good because: (1) It's minimal—easy to implement for anything that produces bytes; (2) It's universal—files, network sockets, compression, memory buffers, pipes all implement it; (3) It's composable—you can wrap readers to add behavior; (4) It's powerful—io.Copy, io.ReadAll, and the entire io package work with any Reader. It's the template for good interface design: find the minimal interface that solves a real problem, then build on it.

**Q11: How do you design an interface in real-world systems like a movie booking service?**

A: Start concrete. Write PaymentGateway as a concrete Stripe implementation. Later, when you add PayPal, extract a PaymentGateway interface with the methods they share: Charge, Refund, GetStatus. This prevents premature abstraction. The interface emerges from multiple implementations, not from speculation. This is why Go's implicit satisfaction is powerful—you don't design interfaces in a vacuum; they emerge from real code.

## What Breaks at Scale

1. **Interface pollution**: Too many large interfaces forces implementers to do too much, makes mocking hard. God interfaces with 30 methods are a smell.
2. **Returning `interface{}`**: Callers lose type safety and must do repeated type assertions with error handling.
3. **Over-abstraction**: Creating interfaces for single implementations "just in case" you'll need polymorphism later. YAGNI applies to interfaces.
4. **Concurrent map access in mocks**: Mock structs often have maps; add sync.Mutex if accessed concurrently.
5. **Nil interface values**: Code that checks `if gateway == nil` misses the case where gateway is an interface holding a nil pointer (common gotcha in error returns).
6. **Not implementing Reader/Writer**: Custom I/O types don't integrate with the standard library without these interfaces. You lose io.Copy, io.ReadAll, etc.
7. **Type switching on interface{} slices**: `[]interface{}` containing mixed types forces type switches on every access.
8. **Shared mock state in tests**: Mock implementations with global state cause test interference. Each test gets its own mock instance.

## Exercise

**Exercise 1: Payment Gateway Abstraction**

Implement:
- A `PaymentGateway` interface with `Charge()`, `Refund()`, `GetStatus()` methods
- Two implementations: `MockPaymentGateway` (in-memory) and `StripeGateway` (stub)
- A `BookingService` that takes a `PaymentGateway` dependency
- Write a test that uses MockPaymentGateway and verifies calls

**Exercise 2: Custom Reader/Writer**

Implement:
- A `RateLimitingReader` that wraps any `io.Reader` and limits read throughput
- A `CompressingWriter` that wraps any `io.Writer` and compresses on write
- Test with `os.File`, `bytes.Buffer`, and pipes

**Exercise 3: Interface Design Review**

You have this interface:
```go
type UserService interface {
	CreateUser(...) error
	GetUser(...) (User, error)
	UpdateUser(...) error
	DeleteUser(...) error
	ListUsers(...) ([]User, error)
	GetUserPaymentMethods(...) ([]PaymentMethod, error)
	CreatePaymentMethod(...) error
	DeletePaymentMethod(...) error
	// ... 20 more methods
}
```

Split this into smaller, focused interfaces. How would you compose them? How would you test each one in isolation?

**Exercise 4: Mock Generation**

Write a hand-written mock for a database interface:
- Implement call tracking (record all Charge calls)
- Implement configurable responses (set what Charge returns)
- Write tests that verify the mock was called with the right arguments

**Exercise 5: nil Interface Trap**

Write a test that demonstrates the difference between a nil interface and an interface holding nil:
```go
var x interface{} = nil     // true
var p *Foo = nil
x = p                        // false!
```

Explain why this is a problem and how to check properly.

**Exercise 6: Mini io.Reader/Writer Implementation**

Implement a custom Reader and Writer:
- UpperCaseReader: wraps any io.Reader and converts all bytes to uppercase
- CountingWriter: wraps any io.Writer and counts how many bytes were written

Test by chaining them with os.File, bytes.Buffer, and io.Pipe to show composition.

**Exercise 7: Composition Over Embedding**

Refactor a struct that embeds types to use composition instead:
- Before: type Connection struct { *net.TCPConn }
- After: type Connection struct { conn *net.TCPConn }

Show how this gives you more control and prevents accidental exposure of embedded methods.

