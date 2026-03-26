# Observability: Tracing, Metrics, and Logging

## Problem

You've just deployed a movie booking system across three services: API Gateway, Booking Service, and Notification Service. A customer reports that booking a ticket took 45 seconds instead of the expected 2-3 seconds. Your team has logs scattered across 10,000 files. You have no trace correlation between services. Your Prometheus dashboards show CPU at 60% but no indication of what's actually slow.

This is the observability crisis at scale. Without the three pillars—logs, metrics, and traces—you're debugging blind. You need to understand: what happened, why it happened, and where the system is heading.

## Theory

### The Three Pillars and Why All Three Matter

**Logs** are discrete events. They answer "what happened?" A log line at timestamp 14:32:15.234 says "booking attempt failed with insufficient seats." But logs are queryable but high-volume and expensive at scale. Logging everything to debug one issue is impractical.

**Metrics** are time-series data. They answer "what's the pattern?" Metrics like `booking_duration_seconds` with labels `{service="booking-service", endpoint="/book"}` let you see "latency increased 10x over the last 5 minutes." Metrics are cheap, always on, and aggregatable. But they hide individual request context.

**Traces** connect the dots. They answer "what's the full path?" A single trace follows one request through all services, showing each operation took how long. Traces are expensive (not sampled, they explode storage costs) but invaluable for understanding dependencies and bottlenecks.

Together:
- A **metric** says "P99 latency is 5s"
- A **trace** shows you which booking for which user caused it
- A **log** explains why (e.g., "database connection pool exhausted")

### OpenTelemetry: The Standard

OpenTelemetry is the CNCF standard for instrumentation. It decouples how you collect data from where you send it.

**Spans** are the unit of work. A span represents one operation: "book a seat," "query database," "call payment service." Each span has:
- `TraceID`: unique per request (propagated across services)
- `SpanID`: unique per operation
- `ParentSpanID`: links to the span that triggered this one
- `Name`: operation name ("POST /book")
- `Start/End time**: when it ran
- `Attributes`: metadata (`user_id=42`, `seat_count=3`)
- `Events**: timed log lines within a span
- `Status`: success, error, or unset

**Traces** are graphs of spans. One HTTP request generates one trace. That trace has many spans: one for the HTTP handler, one for database query, one for message queue. The spans form a DAG (directed acyclic graph) showing causality.

**Context propagation** is how the `TraceID` crosses process boundaries. The API Gateway starts a trace with `TraceID=abc123`. When it calls the Booking Service, it includes `TraceID=abc123` in the HTTP headers. The Booking Service extracts it, creates a child span under the same trace. Distributed tracing collapses.

**Exporters** send spans to backends: Jaeger, Honeycomb, Datadog, Tempo. The exporter is pluggable—change where you send traces without changing code.

### Distributed Tracing Flow

```
Client HTTP Request
    ↓
API Gateway (creates TraceID=xyz, SpanID=1)
  ├─ Span: GET /users/42 (duration: 100ms)
  │   ├─ Event: "cache hit"
  │   └─ Attribute: user_id=42
  └─ calls Booking Service with header: traceparent=00-xyz-1-01
      ↓
Booking Service (extracts TraceID=xyz, creates SpanID=2, ParentSpanID=1)
  ├─ Span: POST /books (duration: 80ms)
  │   ├─ Event: "acquired advisory lock"
  │   └─ Attribute: seats=3
  └─ calls DB with context
      ↓
Database (implicit span via driver instrumentation)
  └─ Span: SELECT ... (duration: 45ms)
```

All three spans share `TraceID=xyz`. A tracing backend visualizes this as a waterfall: you see exactly when each operation ran and how they overlap.

### Structured Logging with Correlation IDs

Logs are unstructured soup without structure. A line like:

```
14:32:15 booking failed
```

is worthless. But:

```json
{
  "timestamp": "2025-03-26T14:32:15.234Z",
  "level": "ERROR",
  "trace_id": "abc123def456",
  "span_id": "span789",
  "service": "booking-service",
  "user_id": 42,
  "seats": 3,
  "error": "insufficient_seats",
  "duration_ms": 45
}
```

This is queryable. You can search logs by `trace_id` and see every operation that happened for that request, in order, across all services.

Go's `log/slog` (1.21+) provides structured logging. Pair it with `trace_id` and `span_id` from your OpenTelemetry context, and logs become traceable.

### Prometheus Metrics: Types

**Counter**: only increases. Example: `bookings_total{status="success"}` increments by 1 each successful booking. Used for "how many requests," "how many errors," "bytes transferred."

**Gauge**: goes up and down. Example: `active_connections` or `queue_depth`. Used for "current state."

**Histogram**: measures distribution. Example: `booking_duration_seconds` with buckets [0.01, 0.05, 0.1, 0.5, 1, 5]. You get counts of how many bookings took 10-50ms, 50-100ms, etc. Prometheus derives _sum and _count automatically.

**Summary**: like histogram but percentile-based. Less useful; histogram + a scraping backend is better.

Labels make metrics queryable: `booking_duration_seconds{service="booking", endpoint="/book", status="success"}`. But beware cardinality: if you label by `user_id` and have 10M users, you've created 10M unique time-series. Prometheus chokes.

### Custom Business Metrics

Infrastructure metrics (CPU, memory) are free via Prometheus node exporter. But custom metrics reveal intent:

- `bookings_total{status}`: how many bookings? Useful for dashboards showing daily/weekly trends
- `booking_duration_seconds`: how fast? Percentiles (P50, P95, P99) matter more than averages
- `available_seats{movie_id}`: business state. Which movies are selling out?
- `refund_amount_total`: revenue impact. Refunds cost money; track them
- `queue_depth`: backlog in background jobs. Notification queue backlog signals slow email service
- `seats_oversold_incidents`: data quality indicator. Track when we sold more seats than exist (bug!)
- `payment_gateway_errors{provider}`: which payment processor is flaky?
- `customer_satisfaction_rating`: user-reported score. Directly measures user happiness

These metrics surface business anomalies faster than logs. A metric spike in refund_amount_total happens seconds before support team hears about it.

**Bucketing and histograms**: for `booking_duration_seconds`, define buckets:
```
0.01s, 0.025s, 0.05s, 0.1s, 0.25s, 0.5s, 1s, 2.5s, 5s, 10s
```

Prometheus records: "how many bookings finished in 50-100ms bucket?" Allows calculating percentiles later (P50, P95, P99). Sum of all buckets = total count.

### Alerting: Symptoms vs Causes

A naive alert: "CPU > 80%, page oncall." Wrong. CPU might be high because you're doing useful work (good) or because of a memory leak (bad).

Better: alert on symptoms (user-facing impact), not causes (infrastructure):

- `booking_latency_p99 > 5s`: symptom
- `booking_error_rate > 0.01`: symptom
- `CPU > 80%`: cause (maybe)

SLI = Service Level Indicator = what you measure (availability, latency, error rate)
SLO = Service Level Objective = target (99.9% availability, P99 < 500ms)
SLA = Service Level Agreement = contractual (we owe you credit if SLO breaches)

Alert when SLI is trending toward SLO breach, not when it's breached.

### Grafana Dashboards: RED and USE

**RED method** (for user-facing services):
- **Rate**: requests per second
- **Errors**: error rate
- **Duration**: latency (P50, P99)

**USE method** (for infrastructure):
- **Utilization**: percentage of resource capacity used
- **Saturation**: how much work is queued
- **Errors**: errors detected

## Production Code

### Fully Instrumented Movie Booking Service

```go
package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracesampler"
	"go.opentelemetry.io/otel/semconv/v1.24.0/httpconv"
	"go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/exporters/prometheus"
)

var (
	tracer = otel.Tracer("booking-service")
	meter  = otel.Meter("booking-service")
)

type BookingService struct {
	db *pgxpool.Pool

	// Metrics
	bookingCounter   metric.Int64Counter
	bookingDuration  metric.Float64Histogram
	availableSeats   metric.Int64UpDownCounter
	errorCounter     metric.Int64Counter
}

func NewBookingService(db *pgxpool.Pool) (*BookingService, error) {
	bookingCounter, _ := meter.Int64Counter(
		"bookings_total",
		metric.WithDescription("Total bookings created"),
	)
	bookingDuration, _ := meter.Float64Histogram(
		"booking_duration_seconds",
		metric.WithDescription("Booking operation duration"),
	)
	availableSeats, _ := meter.Int64UpDownCounter(
		"available_seats",
		metric.WithDescription("Current available seats"),
	)
	errorCounter, _ := meter.Int64Counter(
		"booking_errors_total",
		metric.WithDescription("Booking operation errors"),
	)

	return &BookingService{
		db:               db,
		bookingCounter:   bookingCounter,
		bookingDuration:  bookingDuration,
		availableSeats:   availableSeats,
		errorCounter:     errorCounter,
	}, nil
}

// BookMovie books seats for a user. Instrumented with traces, metrics, and logs.
func (bs *BookingService) BookMovie(ctx context.Context, userID int64, movieID int64, seatCount int32) (bookingID int64, err error) {
	start := time.Now()
	ctx, span := tracer.Start(ctx, "BookMovie",
		trace.WithAttributes(
			attribute.Int64("user.id", userID),
			attribute.Int64("movie.id", movieID),
			attribute.Int32("seats.count", seatCount),
		),
	)
	defer span.End()

	// Structured logging with trace context
	logger := slog.With(
		slog.String("trace_id", span.SpanContext().TraceID().String()),
		slog.String("span_id", span.SpanContext().SpanID().String()),
		slog.Int64("user_id", userID),
		slog.Int64("movie_id", movieID),
	)

	logger.InfoContext(ctx, "starting booking", slog.Int32("seats", seatCount))

	// Acquire advisory lock to prevent concurrent bookings for same user
	lockCtx, lockSpan := tracer.Start(ctx, "AcquireAdvisoryLock")
	err = bs.db.AcquireFunc(lockCtx, func(conn *pgx.Conn) error {
		return conn.QueryRow(lockCtx, "SELECT pg_advisory_lock($1)", userID).Scan()
	})
	lockSpan.End()
	if err != nil {
		logger.ErrorContext(ctx, "failed to acquire lock", slog.String("error", err.Error()))
		bs.errorCounter.Add(ctx, 1, metric.WithAttributes(
			attribute.String("error", "lock_failure"),
		))
		return 0, fmt.Errorf("lock: %w", err)
	}
	defer bs.db.AcquireFunc(ctx, func(conn *pgx.Conn) error {
		return conn.QueryRow(ctx, "SELECT pg_advisory_unlock($1)", userID).Scan()
	})

	// Check seat availability
	checkCtx, checkSpan := tracer.Start(ctx, "CheckAvailability")
	var available int32
	err = bs.db.QueryRow(checkCtx, `
		SELECT COUNT(*) FROM seats
		WHERE movie_id = $1 AND is_available = true
		LIMIT $2
	`, movieID, seatCount).Scan(&available)
	checkSpan.End()
	if err != nil {
		logger.ErrorContext(ctx, "availability check failed", slog.String("error", err.Error()))
		bs.errorCounter.Add(ctx, 1, metric.WithAttributes(
			attribute.String("error", "check_failed"),
		))
		return 0, fmt.Errorf("check: %w", err)
	}

	if available < seatCount {
		logger.WarnContext(ctx, "insufficient seats", slog.Int32("available", available), slog.Int32("requested", seatCount))
		bs.errorCounter.Add(ctx, 1, metric.WithAttributes(
			attribute.String("error", "insufficient_seats"),
		))
		return 0, fmt.Errorf("only %d seats available", available)
	}

	// Insert booking in serializable isolation
	insertCtx, insertSpan := tracer.Start(ctx, "InsertBooking")
	tx, _ := bs.db.BeginTx(insertCtx, pgx.TxOptions{
		IsoLevel: pgx.Serializable,
	})

	err = tx.QueryRow(insertCtx, `
		INSERT INTO bookings (user_id, movie_id, seat_count, status, created_at)
		VALUES ($1, $2, $3, 'CONFIRMED', NOW())
		RETURNING id
	`, userID, movieID, seatCount).Scan(&bookingID)
	insertSpan.End()

	if err != nil {
		tx.Rollback(ctx)
		logger.ErrorContext(ctx, "insert failed", slog.String("error", err.Error()))
		bs.errorCounter.Add(ctx, 1, metric.WithAttributes(
			attribute.String("error", "insert_failed"),
		))
		return 0, fmt.Errorf("insert: %w", err)
	}

	// Mark seats as booked
	updateCtx, updateSpan := tracer.Start(ctx, "UpdateSeats")
	_, err = tx.Exec(updateCtx, `
		UPDATE seats SET is_available = false
		WHERE movie_id = $1 AND is_available = true
		LIMIT $2
	`, movieID, seatCount)
	updateSpan.End()

	if err != nil {
		tx.Rollback(ctx)
		logger.ErrorContext(ctx, "seat update failed", slog.String("error", err.Error()))
		bs.errorCounter.Add(ctx, 1, metric.WithAttributes(
			attribute.String("error", "update_failed"),
		))
		return 0, fmt.Errorf("update: %w", err)
	}

	err = tx.Commit(ctx)
	if err != nil {
		logger.ErrorContext(ctx, "commit failed", slog.String("error", err.Error()))
		bs.errorCounter.Add(ctx, 1, metric.WithAttributes(
			attribute.String("error", "commit_failed"),
		))
		return 0, fmt.Errorf("commit: %w", err)
	}

	duration := time.Since(start).Seconds()
	bs.bookingCounter.Add(ctx, 1, metric.WithAttributes(
		attribute.String("status", "success"),
	))
	bs.bookingDuration.Record(ctx, duration, metric.WithAttributes(
		attribute.String("status", "success"),
	))

	logger.InfoContext(ctx, "booking completed",
		slog.Int64("booking_id", bookingID),
		slog.Float64("duration_sec", duration),
	)

	return bookingID, nil
}

func initTracer(ctx context.Context) (*trace.TracerProvider, error) {
	exporter, err := otlptracehttp.New(ctx,
		otlptracehttp.WithEndpoint(os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT")),
	)
	if err != nil {
		return nil, err
	}

	tp := trace.NewTracerProvider(
		trace.WithBatcher(exporter),
		// Sample 100% of traces (in production, use ProbabilitySampler(0.1) for 10%)
		trace.WithSampler(tracesampler.AlwaysSample()),
	)
	return tp, nil
}

func initMetrics(ctx context.Context) error {
	exporter, err := prometheus.New()
	if err != nil {
		return err
	}

	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(exporter))
	otel.SetMeterProvider(mp)
	return nil
}

func initLogger() {
	opts := &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}
	handler := slog.NewJSONHandler(os.Stdout, opts)
	slog.SetDefault(slog.New(handler))
}

func main() {
	initLogger()

	ctx := context.Background()

	// Initialize tracing
	tp, _ := initTracer(ctx)
	otel.SetTracerProvider(tp)
	defer tp.Shutdown(ctx)

	// Initialize metrics
	initMetrics(ctx)

	// Database
	db, _ := pgxpool.New(ctx, "postgres://...")
	defer db.Close()

	bs, _ := NewBookingService(db)

	// HTTP handler with automatic tracing middleware
	mux := http.NewServeMux()
	mux.HandleFunc("POST /book", func(w http.ResponseWriter, r *http.Request) {
		// Request arrives with traceparent header from client
		ctx := r.Context()

		// Extract user and movie from request...
		userID, movieID, seatCount := int64(42), int64(1), int32(2)

		bookingID, err := bs.BookMovie(ctx, userID, movieID, seatCount)
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"booking_id":%d}`, bookingID)
	})

	// Wrap with OTEL HTTP instrumentation (auto-traces, adds traceparent header)
	handler := otelhttp.NewHandler(mux, "booking-api",
		otelhttp.WithSpanNameFormatter(func(operation string, r *http.Request) string {
			return r.Method + " " + r.URL.Path
		}),
	)

	http.ListenAndServe(":8080", handler)
}
```

### Debugging with Traces

When P99 latency spikes, open your trace backend (Jaeger UI). Search for traces by `duration > 5s`. Click one. You see:

```
GET /book (5234ms total)
├─ POST booking-service/book (5100ms)
│  ├─ AcquireAdvisoryLock (50ms)
│  ├─ CheckAvailability (100ms)
│  ├─ InsertBooking (4800ms) ← SLOW
│  │  ├─ SELECT (4750ms) ← BLAME
│  │  └─ UPDATE (50ms)
│  └─ Commit (50ms)
└─ Response encode (84ms)
```

Clearly the `SELECT` in `InsertBooking` is the culprit. Check EXPLAIN ANALYZE on that query. Missing index? Lock contention? Now you debug the actual problem.

## Tradeoffs and What Breaks

### Alert Fatigue

If you alert on every anomaly, oncall ignores alerts. Better: alert on symptoms (user impact), with intelligent thresholds that adapt to baselines. Use tools like Prophet (Facebook) or Moogsoft for dynamic thresholding.

### Missing Trace Context Propagation

If the API Gateway doesn't extract `traceparent` headers or doesn't pass them to downstream services, traces fragment. Use OpenTelemetry's HTTP instrumentation automatically (shown above) to avoid manual propagation bugs.

### Log Volume Explosion

Logging every operation at INFO level creates terabytes of data. Solution: use sampling (log 1% of requests), structured logging (aggregate by field), and retention policies (delete after 7 days). Only log errors and high-level events.

### Cardinality Bombs and Preventing Explosion

If you label metrics by `user_id`, you create one time-series per user. With 10M users, Prometheus crashes. Solution: label by static dimensions only (`service`, `endpoint`, `status`). For user-specific metrics, use logs or traces instead.

**Cardinality** is the number of unique time-series for a metric. For example:
- `booking_duration_seconds{service="booking", endpoint="/book", status="success"}` = 1 time-series
- Add `user_id` label: 1 million users = 1 million time-series (explosion!)

Prometheus in-memory stores all time-series. With 1M series per metric, 10 metrics = 10M series = 5GB+ memory. Queries slow down (O(N) cardinality).

Prevention:
- Whitelist labels strictly. Only `service`, `endpoint`, `status`, `method`, `code`.
- Never label by user ID, account ID, request ID, or anything with high cardinality.
- If you need per-user analysis, use logs/traces or pre-compute aggregations.

Example antipattern:
```go
// WRONG: labels explosion
histogram.Record(ctx, duration, metric.WithAttributes(
  attribute.String("booking_id", fmt.Sprint(bookingID)), // CARDINALITY BOMB
))

// RIGHT: only static labels
histogram.Record(ctx, duration, metric.WithAttributes(
  attribute.String("status", "success"), // ~10 values max
))
```

Detect cardinality issues: query Prometheus `count({__name__=~".+"})` to see total time-series count. If > 1M, investigate which metrics are exploding.

### Trace Backend Costs

Sampling all traces costs $5K+/month for any volume. Solution:
- Sample by error (always collect error traces)
- Sample by latency (always collect slow traces)
- Sample randomly (10% of happy paths)
- Conditional sampling (collect traces for VIP users)

## Interview Corner

**Q1: You're seeing a 10x latency increase in the booking service, but CPU is at 30% and memory is normal. What's the first thing you'd check with observability?**

A: I'd look at traces. The metric shows latency is bad, but CPU/memory are normal, so it's not a resource contention issue. Traces would show whether:
- The database query got slow (missing index, lock contention)
- A downstream service (payment, inventory) started responding slowly
- The serializable transaction is causing conflicts (retries)
- A new bottleneck appeared in the dependency graph

Without traces, I'm guessing. With traces, I see exactly where the time went. I'd open the trace backend (Jaeger UI), filter by latency > 5s, and look at the waterfall. If I see the database operation taking 4.5s out of 5s total, that's where to focus.

**Q2: How would you design alerting to catch slow booking queries without creating alert fatigue?**

A: Two approaches:
1. Alert on SLO breach: if P99 booking latency > 500ms for 5 consecutive minutes, page oncall. This is user-impact focused.
2. Alert on error rate: if booking error rate > 1%, page oncall. This catches issues before latency matters.

Avoid alerting on raw latency (P99 might be 200ms normally, 400ms during off-peak). Instead, use dynamic thresholds or alert on the *change* (latency increased 5x from baseline).

Better: use Prometheus rules to calculate SLO burn rate. If you're burning through your SLO budget too fast (e.g., 10% error rate for SLO 99.9%), page immediately. Otherwise, wait until human review at end of quarter.

**Q3: You have 10M active users. Should you label booking metrics by `user_id`?**

A: Absolutely not. That creates 10M unique time-series, which crashes Prometheus. Instead:
- Label by static dimensions: `service`, `endpoint`, `status`
- For user-specific insights, use logs or traces (they're cheaper and more detailed)
- If you need per-user SLOs, query traces for specific users on demand

High cardinality is a common Prometheus problem. Rule of thumb: if a label value could be in the thousands or higher, it's too high cardinality. Stick to labels with < 10 values.

**Q4: How would you correlate logs, metrics, and traces for a single slow booking request?**

A: Via trace ID. The trace spans a request end-to-end. Every operation in that trace should emit structured logs with the same `trace_id`. Then:
1. Metric shows P99 latency increased
2. Find a trace with high latency in the trace backend (Jaeger, Tempo, Honeycomb)
3. Extract `trace_id` from that trace (e.g., `abc123`)
4. Search logs by `trace_id:abc123` (in your log aggregator: ELK, DataDog, CloudWatch)
5. See all operations that happened, in order, with structured context (user_id, movie_id, seat_count, etc)

This gives you the full picture: logs explain the "why," traces show the "what/when," metrics show the "trend." Most senior engineers use trace ID as the golden thread to tying everything together.

**Q5: What are the tradeoffs of sampling traces at 10% vs 100%?**

A:
- **10% sampling**: 90% cheaper. But you might miss the one problematic request (race condition that happens 1/1000 times). At 1000 RPS, 10% sampling = 100 traces stored per second * 86400s = 8.64M traces/day.
- **100% sampling**: 10x cost, but catch everything. Infeasible at scale (1000 RPS * 100% = 864M traces/day = $5K+/month storage).

Better: intelligent sampling:
- Always sample errors (100% of 500 responses): error traces are gold for debugging
- Always sample slow requests (P99, latency > 500ms): find bottlenecks
- Randomly sample fast successes (1%): establish baseline performance

This gives you all the data you need at 5% total cost. At Uber scale (millions of RPS), they use tail-based sampling: only keep traces that exceeded SLO, not random samples.

**Q6: Your team logs everything at DEBUG level. Log volume doubled, storage costs exploded. How do you optimize?**

A: Triage logging levels:
- **ERROR**: exceptions, failed operations (always log)
- **WARN**: degraded behavior, retries, timeouts (always log)
- **INFO**: important business events (login, booking), but cap volume
- **DEBUG**: detailed execution flow (only in development)

For INFO, use sampling: log 1 in 1000 happy-path requests. Log 100% of errors. This keeps signal high, noise low.

In structured logs, add context fields (trace_id, user_id, movie_id) so you can query efficiently. Search "errors for user 42" instead of grepping through text.

Use log rotation: keep last 7 days, archive older to cold storage. Most debugging happens on recent logs anyway.

## Exercise

Instrument a WhatsApp-like message service with OpenTelemetry. The service should:

1. Accept `POST /messages` with `{to_user_id, text}` - create a message
2. Accept `GET /messages?user_id=X&limit=10&cursor=abc` - list messages with cursor pagination
3. Save to PostgreSQL with pgx
4. Publish to message queue (in-memory channel for now)
5. Emit structured logs with trace ID, span ID, and business context
6. Record metrics: `messages_total`, `message_duration_seconds`, `queue_depth`, `message_size_bytes`

Requirements:
- Every log line must include `trace_id`, `span_id`, `user_id`, and `to_user_id`
- Create child spans for DB insert, queue publish, and permission check
- Use `pgxpool` with min 5, max 20 connections
- Metrics should have labels: `status` (success/error/dropped), `operation` (insert/list)
- Extract `traceparent` header from incoming HTTP requests (W3C format)
- Implement graceful shutdown with 5-second timeout for in-flight requests
- Add a health check endpoint that pings the database
- Log all errors with full context, but don't log message text (PII risk)

Expected output when you POST a message:
- One trace visible in Jaeger (or stdout if exporting to otlptracehttp)
- Logs in JSON format with trace ID for correlation
- Metrics in Prometheus `/metrics` endpoint with proper cardinality

Bonus challenges:
1. Simulate a slow database query (sleep 500ms in INSERT) and show how traces pinpoint it
2. Simulate a queue timeout (message publish hangs for 2s) and verify the span shows it
3. Add a trace sampler: sample all errors, sample 10% of successes
4. Implement a logging sampler: log 100% of errors, sample 1% of successes
5. Add custom business metric: `message_words_total` histogram (distribution of message lengths)

---

# Observability: Tracing, Metrics, and Logging

