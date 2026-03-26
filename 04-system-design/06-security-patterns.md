# Security Patterns for Backend Systems

## Problem

A customer's password is stored in plaintext in your database. A competitor scrapes the API with a fake token. Your API accepts `user_id` from clients, allowing them to modify other users' bookings. A payment webhook updates booking status without verifying the signature. An admin's API key is committed to GitHub. Your service talks to other services without verifying identity. A GDPR audit discovers logs containing user PII everywhere. An attacker SQL-injects a parameter and dumps the database.

Security at scale means layered defense: strong auth, fine-grained authz, encrypted transport, input validation, audit logging, and secret management. This lesson covers patterns used by $100M+ SaaS companies.

## Theory

### Authentication: Password Hashing

Never store plaintext passwords. Use **bcrypt**:

```go
import "golang.org/x/crypto/bcrypt"

// Hashing (slow: ~100ms per hash intentionally)
hash, _ := bcrypt.GenerateFromPassword([]byte("user-password"), bcrypt.DefaultCost)
// hash = $2a$10$... (160 chars)

// Verification
err := bcrypt.CompareHashAndPassword(hash, []byte("user-password"))
if err != nil {
  // Wrong password
}
```

Bcrypt has a **cost** parameter (default 10): cost 10 = 2^10 = 1024 hash iterations. Each cost increment doubles time. So cost 11 takes ~200ms. This makes brute force expensive: cracking 1M passwords with cost 11 takes 200M seconds = 6 years.

Alternative: **argon2** (better but less common):

```go
import "github.com/alexedwards/argon2id"

hash, _ := argon2id.CreateHash("password", argon2id.DefaultParams)
match, _ := argon2id.ComparePasswordAndHash("password", hash)
```

Argon2 is memory-hard: brute force requires billions of GB of RAM per attempt (exorbitant).

### Session Management

After password verification, create a **session token**. Options:

**Stateful sessions** (session in database):
```go
sessionID := generateRandomToken() // 32-byte random
db.Exec("INSERT INTO sessions(session_id, user_id, expires_at) VALUES($1, $2, NOW() + INTERVAL '7 days')", sessionID, userID)

// Client gets sessionID in Set-Cookie
cookie := &http.Cookie{
  Name: "session_id",
  Value: sessionID,
  HttpOnly: true,
  Secure: true, // HTTPS only
  SameSite: http.SameSiteLax,
}
```

On request, verify session in database. No session? Reject. Session expired? Reject.

**Stateless sessions** use JWT (see below).

Stateful is simpler, better for logout (delete session). Stateless scales better (no session database).

### JWT: Signing, Claims, Refresh Tokens

JWT is a token format: `Header.Payload.Signature`

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI0MiIsImlhdCI6MTYwMDAwMDAwMCwiZXhwIjoxNjAwMDAzNjAwfQ.signature
```

Payload (base64):
```json
{
  "sub": "42",           // subject (user ID)
  "iat": 1600000000,     // issued at
  "exp": 1600003600,     // expiry (1 hour)
  "scope": "booking:write"
}
```

Signature: `HMAC(header + payload, secret_key)`

Verification:
```go
import "github.com/golang-jwt/jwt/v5"

token, err := jwt.Parse(tokenString, func(token *jwt.Token) (interface{}, error) {
  return secretKey, nil // verify with secret
})

if claims, ok := token.Claims.(jwt.MapClaims); ok && token.Valid {
  userID := claims["sub"].(string)
  // Claims verified
}
```

Critical: **short TTL** (15 min). If token leaked, damage is limited. Refresh token to get new access token (separate, long-lived token).

```go
// Access token (short TTL)
accessToken, _ := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
  "sub": userID,
  "exp": time.Now().Add(15 * time.Minute).Unix(),
}).SignedString(secret)

// Refresh token (long TTL, signed with different secret or stored in DB)
refreshToken := generateRandomToken()
db.Exec("INSERT INTO refresh_tokens(token, user_id, expires_at) VALUES($1, $2, NOW() + INTERVAL '7 days')", refreshToken, userID)

// Client stores both
// Use accessToken for API calls
// When accessToken expires, use refreshToken to get new accessToken
```

### OAuth 2.0 and OIDC

OAuth 2.0 is for delegation. User wants to give app permission to read their Google Drive:

```
1. App redirects user: https://accounts.google.com/o/oauth2/auth?client_id=...&redirect_uri=...
2. User logs in to Google, sees "App wants access", clicks approve
3. Google redirects back: https://app.com/callback?code=abc123
4. App exchanges code for token (backend-to-backend):
   POST https://oauth.google.com/token
   client_id=..., client_secret=..., code=abc123
   Response: {"access_token": "...", "refresh_token": "..."}
5. App uses access_token to call Google APIs on user's behalf
```

**OIDC** (OpenID Connect) is OAuth 2.0 + authentication. Google also returns user info (email, name).

For SaaS: use OAuth for user login (delegate to Google/GitHub/etc), JWT for service-to-service auth.

### API Security: Input Validation, SQL Injection Prevention

Every input is untrusted. Validate and sanitize:

```go
// WRONG: string concatenation (SQL injection!)
query := fmt.Sprintf("SELECT * FROM users WHERE email = '%s'", email) // attacker: ' OR '1'='1
db.Query(query)

// RIGHT: parameterized queries (pgx does this)
db.QueryRow("SELECT * FROM users WHERE email = $1", email)
```

With pgx, all queries use parameters. pgx encodes values separately from SQL, preventing injection.

Additional validation:
```go
// Check type
limit, err := strconv.ParseInt(r.URL.Query().Get("limit"), 10, 32)
if err != nil || limit < 0 || limit > 100 {
  http.Error(w, "invalid limit", http.StatusBadRequest)
  return
}

// Whitelist allowed values
sort := r.URL.Query().Get("sort")
if sort != "asc" && sort != "desc" {
  http.Error(w, "invalid sort", http.StatusBadRequest)
  return
}

// Length limits
if len(name) > 255 {
  http.Error(w, "name too long", http.StatusBadRequest)
  return
}
```

### Secrets Management

Never hardcode secrets in code. Options:

**Environment variables**:
```go
databaseURL := os.Getenv("DATABASE_URL")
if databaseURL == "" {
  log.Fatal("DATABASE_URL not set")
}
```

Downside: visible in process list, Docker logs.

**Vault** (HashiCorp):
```go
import "github.com/hashicorp/vault/api"

client, _ := api.NewClient(...)
secret, _ := client.Logical().Read("secret/database")
password := secret.Data["password"].(string)
```

App authenticates to Vault (via token, Kubernetes auth, or IAM role), fetches secrets on startup or per request. Secrets never written to disk.

**Sealed Secrets** (Kubernetes):
```
kubectl create secret generic db-password --from-literal=password=secret
kubectl seal -f secret.yaml > sealed-secret.yaml  # Encrypted
```

Sealed secrets are encrypted with cluster-specific key. Only that cluster can decrypt. Safe to commit to git.

**Rotation**: periodically change secrets. For database passwords, Vault can auto-rotate (Vault updates password in database, app fetches new password).

### Transport Security: TLS, mTLS

**TLS** (HTTPS): encrypts client↔server communication, authenticates server (via certificate).

```go
http.ListenAndServeTLS(":443", "cert.pem", "key.pem", mux)
```

Certificate signed by trusted CA (Let's Encrypt). Client verifies certificate before sending data.

**mTLS** (mutual TLS): both client and server authenticate each other. Used for service-to-service communication.

```go
// Server requires client certificate
tlsConfig := &tls.Config{
  ClientAuth: tls.RequireAndVerifyClientCert,
  ClientCAs: caCertPool,
}
server := &http.Server{
  Addr: ":8443",
  TLSConfig: tlsConfig,
}

// Client presents certificate
cert, _ := tls.LoadX509KeyPair("client-cert.pem", "client-key.pem")
tlsConfig := &tls.Config{
  Certificates: []tls.Certificate{cert},
}
client := &http.Client{
  Transport: &http.Transport{TLSClientConfig: tlsConfig},
}
```

Prevent MITM attacks between services. Certificate rotation must be automated (Kubernetes cert-manager, service mesh like Istio).

### CORS, CSRF, XSS Prevention

**CORS** (Cross-Origin Resource Sharing): browser restricts scripts from one domain calling APIs on another. Set headers:

```go
w.Header().Set("Access-Control-Allow-Origin", "https://app.example.com")
w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT")
w.Header().Set("Access-Control-Allow-Credentials", "true") // if cookies
```

Restrict to trusted origins. `Access-Control-Allow-Origin: *` is insecure if API is sensitive.

**CSRF** (Cross-Site Request Forgery): attacker submits form on user's behalf.

```
User logged in to bank.com
Attacker's site: <img src="bank.com/transfer?to=attacker&amount=1000">
Browser auto-includes bank.com cookies, transfer happens
```

Prevention: CSRF tokens. Server issues token:
```go
token := generateRandomToken()
w.Header().Set("Set-Cookie", fmt.Sprintf("csrf=%s; HttpOnly", token))

// Form must include token
w.Header().Set("Content-Type", "text/html")
w.Write([]byte(`
<form action="/transfer" method="POST">
  <input name="csrf" value="` + token + `">
  <input name="amount" value="1000">
  <button>Transfer</button>
</form>
`))

// Verify on POST
csrf := r.FormValue("csrf")
cookie, _ := r.Cookie("csrf")
if csrf != cookie.Value {
  http.Error(w, "CSRF token mismatch", http.StatusForbidden)
  return
}
```

**XSS** (Cross-Site Scripting): attacker injects script in response.

```html
<!-- User enters: <script>alert('xss')</script> -->
<!-- Server returns without escaping: -->
<div>User comment: <script>alert('xss')</script></div>
<!-- Script runs in user's browser -->
```

Prevention: HTML-escape output:
```go
import "html"

userComment := r.FormValue("comment")
w.Write([]byte("<div>Comment: " + html.EscapeString(userComment) + "</div>"))
// Outputs: <div>Comment: &lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;</div>
```

Browsers don't execute escaped HTML. For user-generated content, use allowlist-based sanitizer.

### Audit Logging

Log all important actions for compliance:

```go
db.Exec(`
  INSERT INTO audit_logs (user_id, action, resource, resource_id, status, created_at)
  VALUES ($1, $2, $3, $4, $5, NOW())
`, userID, "BOOKING_CREATED", "booking", bookingID, "success")
```

Audit logs must be:
- **Immutable**: can't edit/delete (insert-only table, maybe with blockchain)
- **Comprehensive**: all auth events, data access, changes
- **Traceable**: include trace IDs to correlate with app logs

Log rotation: keep 7 years for compliance (SOC2, GDPR).

## Production Code

### Complete Auth Middleware for Movie Booking API

```go
package main

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"golang.org/x/crypto/bcrypt"
)

var jwtSecret = []byte("your-secret-key-min-32-chars-long") // Load from Vault

type Claims struct {
	UserID int64  `json:"sub"`
	Email  string `json:"email"`
	Scope  string `json:"scope"`
	jwt.RegisteredClaims
}

type AuthService struct {
	db *pgxpool.Pool
}

// HashPassword hashes a password using bcrypt
func (as *AuthService) HashPassword(password string) (string, error) {
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	return string(hash), err
}

// VerifyPassword checks if password matches hash
func (as *AuthService) VerifyPassword(hash, password string) bool {
	err := bcrypt.CompareHashAndPassword([]byte(hash), []byte(password))
	return err == nil
}

// CreateAccessToken generates a JWT access token (short-lived)
func (as *AuthService) CreateAccessToken(userID int64, email string) (string, error) {
	claims := Claims{
		UserID: userID,
		Email:  email,
		Scope:  "booking:read booking:write",
		RegisteredClaims: jwt.RegisteredClaims{
			IssuedAt:  jwt.NewNumericDate(time.Now()),
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(15 * time.Minute)),
		},
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return token.SignedString(jwtSecret)
}

// CreateRefreshToken generates a refresh token (long-lived)
func (as *AuthService) CreateRefreshToken(ctx context.Context, userID int64) (string, error) {
	refreshToken := generateRandomToken(32)
	expiresAt := time.Now().Add(7 * 24 * time.Hour)

	_, err := as.db.Exec(ctx, `
		INSERT INTO refresh_tokens (user_id, token, expires_at)
		VALUES ($1, $2, $3)
	`, userID, refreshToken, expiresAt)

	return refreshToken, err
}

// RefreshAccessToken exchanges refresh token for new access token
func (as *AuthService) RefreshAccessToken(ctx context.Context, refreshToken string) (string, error) {
	var userID int64
	var email string

	err := as.db.QueryRow(ctx, `
		SELECT user_id, u.email FROM refresh_tokens rt
		JOIN users u ON rt.user_id = u.id
		WHERE rt.token = $1 AND rt.expires_at > NOW()
	`, refreshToken).Scan(&userID, &email)

	if err != nil {
		return "", fmt.Errorf("invalid refresh token")
	}

	// Rotate refresh token: delete old, create new
	as.db.Exec(ctx, "DELETE FROM refresh_tokens WHERE token = $1", refreshToken)
	newRefreshToken, _ := as.CreateRefreshToken(ctx, userID)

	// Return new access token
	accessToken, _ := as.CreateAccessToken(userID, email)
	return accessToken, nil
}

// VerifyToken validates JWT token
func (as *AuthService) VerifyToken(tokenString string) (*Claims, error) {
	claims := &Claims{}
	token, err := jwt.ParseWithClaims(tokenString, claims, func(token *jwt.Token) (interface{}, error) {
		if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
		}
		return jwtSecret, nil
	})

	if err != nil {
		return nil, err
	}

	if !token.Valid {
		return nil, fmt.Errorf("invalid token")
	}

	return claims, nil
}

// AuditLog logs security-relevant events
func (as *AuthService) AuditLog(ctx context.Context, userID int64, action, resource, resourceID string, status string) {
	_, err := as.db.Exec(ctx, `
		INSERT INTO audit_logs (user_id, action, resource, resource_id, status, ip_address, user_agent, created_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
	`, userID, action, resource, resourceID, status, "", "") // IP/UserAgent from HTTP request

	if err != nil {
		log.Printf("audit log failed: %v", err)
	}
}

// Middleware: authenticate and authorize
func AuthMiddleware(as *AuthService) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			// Extract JWT from Authorization header
			authHeader := r.Header.Get("Authorization")
			if authHeader == "" {
				http.Error(w, "missing authorization header", http.StatusUnauthorized)
				return
			}

			parts := strings.Split(authHeader, " ")
			if len(parts) != 2 || parts[0] != "Bearer" {
				http.Error(w, "invalid authorization header", http.StatusUnauthorized)
				return
			}

			claims, err := as.VerifyToken(parts[1])
			if err != nil {
				http.Error(w, "invalid token", http.StatusUnauthorized)
				return
			}

			// Attach claims to context
			ctx := context.WithValue(r.Context(), "user_id", claims.UserID)
			ctx = context.WithValue(ctx, "claims", claims)

			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// Middleware: rate limiting with token bucket
type RateLimiter struct {
	tokens    float64
	capacity  float64
	refillRate float64 // tokens per second
	lastRefill time.Time
}

func NewRateLimiter(capacity, refillRate float64) *RateLimiter {
	return &RateLimiter{
		tokens:     capacity,
		capacity:   capacity,
		refillRate: refillRate,
		lastRefill: time.Now(),
	}
}

func (rl *RateLimiter) Allow() bool {
	now := time.Now()
	elapsed := now.Sub(rl.lastRefill).Seconds()
	rl.tokens = min(rl.capacity, rl.tokens+elapsed*rl.refillRate)
	rl.lastRefill = now

	if rl.tokens >= 1 {
		rl.tokens--
		return true
	}
	return false
}

func RateLimitMiddleware(limiter *RateLimiter) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if !limiter.Allow() {
				w.Header().Set("Retry-After", "1")
				http.Error(w, "rate limited", http.StatusTooManyRequests)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// Request handlers

type LoginRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

type AuthResponse struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	ExpiresIn    int    `json:"expires_in"`
}

func (as *AuthService) Login(w http.ResponseWriter, r *http.Request) {
	var req LoginRequest
	json.NewDecoder(r.Body).Decode(&req)

	ctx := r.Context()

	// Fetch user
	var userID int64
	var passwordHash string
	err := as.db.QueryRow(ctx, `
		SELECT id, password_hash FROM users WHERE email = $1 AND deleted_at IS NULL
	`, req.Email).Scan(&userID, &passwordHash)

	if err != nil {
		as.AuditLog(ctx, 0, "LOGIN_FAILED", "user", req.Email, "user_not_found")
		http.Error(w, "invalid credentials", http.StatusUnauthorized)
		return
	}

	// Verify password
	if !as.VerifyPassword(passwordHash, req.Password) {
		as.AuditLog(ctx, userID, "LOGIN_FAILED", "user", req.Email, "wrong_password")
		http.Error(w, "invalid credentials", http.StatusUnauthorized)
		return
	}

	// Create tokens
	accessToken, _ := as.CreateAccessToken(userID, req.Email)
	refreshToken, _ := as.CreateRefreshToken(ctx, userID)

	as.AuditLog(ctx, userID, "LOGIN_SUCCESS", "user", req.Email, "success")

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(AuthResponse{
		AccessToken:  accessToken,
		RefreshToken: refreshToken,
		ExpiresIn:    900, // 15 min
	})
}

func (as *AuthService) RefreshToken(w http.ResponseWriter, r *http.Request) {
	type RefreshRequest struct {
		RefreshToken string `json:"refresh_token"`
	}

	var req RefreshRequest
	json.NewDecoder(r.Body).Decode(&req)

	ctx := r.Context()
	accessToken, err := as.RefreshAccessToken(ctx, req.RefreshToken)
	if err != nil {
		http.Error(w, "invalid refresh token", http.StatusUnauthorized)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"access_token": accessToken,
		"expires_in":   900,
	})
}

// Authorization middleware: check scope
func AuthorizeScope(requiredScope string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			claims := r.Context().Value("claims").(*Claims)

			if !strings.Contains(claims.Scope, requiredScope) {
				http.Error(w, "insufficient permissions", http.StatusForbidden)
				return
			}

			next.ServeHTTP(w, r)
		})
	}
}

// Resource ownership check
func CheckOwnership(ownerID int64) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			userID := r.Context().Value("user_id").(int64)

			if userID != ownerID {
				http.Error(w, "forbidden", http.StatusForbidden)
				return
			}

			next.ServeHTTP(w, r)
		})
	}
}

// Webhook verification: verify HMAC signature from external service
func VerifyWebhookSignature(payload []byte, signature string, secret string) bool {
	import "crypto/hmac"
	import "crypto/sha256"
	import "encoding/hex"

	h := hmac.New(sha256.New, []byte(secret))
	h.Write(payload)
	expectedSig := hex.EncodeToString(h.Sum(nil))

	return subtle.ConstantTimeCompare([]byte(signature), []byte(expectedSig)) == 1
}

func (as *AuthService) HandlePaymentWebhook(w http.ResponseWriter, r *http.Request) {
	signature := r.Header.Get("X-Webhook-Signature")
	payload, _ := ioutil.ReadAll(r.Body)

	// Verify webhook came from payment provider
	if !VerifyWebhookSignature(payload, signature, "webhook_secret") {
		http.Error(w, "invalid signature", http.StatusForbidden)
		return
	}

	// Process webhook safely
	var event map[string]interface{}
	json.Unmarshal(payload, &event)

	as.AuditLog(r.Context(), 0, "WEBHOOK_RECEIVED", "payment", event["id"].(string), "verified")

	w.WriteHeader(http.StatusOK)
}

func generateRandomToken(length int) string {
	b := make([]byte, length)
	rand.Read(b)
	return base64.StdEncoding.EncodeToString(b)
}

func min(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}

func main() {
	db, _ := pgxpool.New(context.Background(), "postgres://...")
	authService := &AuthService{db: db}

	mux := http.NewServeMux()

	// Public endpoints
	mux.HandleFunc("POST /auth/login", authService.Login)
	mux.HandleFunc("POST /auth/refresh", authService.RefreshToken)

	// Protected endpoints
	authMiddleware := AuthMiddleware(authService)
	rateLimiter := NewRateLimiter(100, 10) // 100 tokens, refill 10/sec
	rateLimitMiddleware := RateLimitMiddleware(rateLimiter)

	bookingsHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// User authenticated and authorized
		userID := r.Context().Value("user_id").(int64)
		fmt.Fprintf(w, "Bookings for user %d", userID)
	})

	mux.Handle("GET /bookings", authMiddleware(rateLimitMiddleware(bookingsHandler)))

	http.ListenAndServe(":8080", mux)
}
```

## Tradeoffs and What Breaks

### JWT Without Expiry

Token never expires. If leaked, attacker has permanent access. Solution: short TTL (15 min), refresh tokens.

### Secrets in Code

API key hardcoded in main.go, committed to GitHub. Attacker has access. Solution: use Vault, environment variables, or Sealed Secrets.

### SQL Injection via String Concatenation

```go
// WRONG
query := fmt.Sprintf("SELECT * FROM bookings WHERE user_id = %d", userID)
db.Query(query)

// RIGHT (pgx parameterizes)
db.QueryRow("SELECT * FROM bookings WHERE user_id = $1", userID)
```

Always use parameterized queries.

### Missing Rate Limits

API hammered by bot. Real users can't book. Solution: token bucket, per-user or per-IP limits.

### Zero-Trust Gaps

Services communicate without mTLS. Attacker on network sniffs traffic, modifies requests. Solution: enforce mTLS between services.

## Interview Corner

**Q1: A customer's password is in plaintext. How do you respond to audit?**

A: Immediate steps:
1. Reset all passwords (force re-entry)
2. Notify customers (security disclosure)
3. Implement bcrypt hashing
4. Audit logs: who accessed password data?
5. Monitor for unauthorized access

Prevent: use secret management, code review process, security tests (ensure passwords never logged).

**Q2: API key committed to GitHub. How do you mitigate?**

A: Immediate:
1. Rotate key (revoke old, issue new)
2. Check access logs (what did attacker do?)
3. Monitor for suspicious activity

Prevent: pre-commit hook to scan for secrets, use Vault instead of hardcoded keys.

**Q3: How do you handle token expiry and refresh?**

A: Access token TTL: 15 min (short, limits damage if leaked). Refresh token TTL: 7 days (long, user doesn't re-login often).

Client flow:
1. POST /login -> access + refresh token
2. Use access token for requests
3. When 401 (expired), POST /refresh with refresh token -> new access token
4. If refresh token expired, redirect to login

Refresh tokens stored in database, can be revoked (logout = delete refresh token).

**Q4: Webhook from payment provider. How do you verify it's really from them?**

A: Verify HMAC signature:
1. Provider includes header: `X-Webhook-Signature: hmac_sha256(payload, secret)`
2. Server computes: `expected = hmac_sha256(payload, secret)`
3. Compare: `subtle.ConstantTimeCompare(received, expected)`
4. Constant-time compare prevents timing attacks

Also: check timestamp (prevent replay), validate event schema.

**Q5: Design auth for microservices with multiple services.**

A: Service-to-service:
1. Each service has certificate (mTLS)
2. Service A calls Service B with client cert
3. Service B verifies cert chain
4. Token propagation: if user made request to Service A, A passes JWT to B in Authorization header

User↔Service A: JWT or session cookie
Service A↔Service B: mTLS + JWT

Kubernetes-specific: use service accounts and tokens. Each service gets a service account (like a user identity). Kubelet auto-mounts service account token. Service A calls Service B with that token. Service B verifies token signature (signed by Kubernetes CA).

**Q6: How do you handle password reset securely?**

A: Flow:
1. User requests reset: `POST /auth/password-reset-request` with email
2. Server generates time-limited token (10 min): `token = base64(random(32)) + timestamp`
3. Send email: "click here to reset: https://app.com/reset?token=abc123"
4. User clicks, enters new password: `POST /auth/password-reset` with token + new password
5. Server verifies token (not expired, exists in database), updates password hash, deletes token

Never send password in reset email or logging. Never put password in URL query string (logged in browser history, server logs, proxy logs).

Token should be single-use (delete after one successful use). Revoke all refresh tokens on reset (force user to re-login to all devices).

**Q7: You discovered logs contain user credit card numbers. How do you respond?**

A: Immediate actions:
1. Stop all logging (emergency mode)
2. Identify extent: search logs for patterns (PAN regex), count occurrences
3. Purge: delete any logs containing PAN (irreversible)
4. Audit: when did this start? Which code version introduced it?
5. Fix: add PII redaction filter (mask credit cards, SSNs, etc before logging)
6. Compliance: notify security team, consider breach notification (if logs backed up to cold storage, they contain sensitive data)

Prevention:
- Never log request/response bodies directly
- Use structured logging with explicit fields (don't log arbitrary objects)
- Add redaction filter: mask `card_number`, `ssn`, `api_key` fields
- Code review: check logs for sensitive data
- Automated testing: run PII scanner on logs (detect patterns like PAN)

## Exercise

Build a secure booking API with:

1. Registration: hash password with bcrypt
2. Login: verify password, issue JWT + refresh token
3. Protected endpoint: require valid JWT
4. Authorization: user can only see their own bookings
5. Rate limiting: 100 req/min per user
6. Audit logging: log all auth events
7. Webhook verification: verify HMAC signature from payment provider

Bonus: implement token refresh endpoint, password reset flow, 2FA with TOTP.

---

