package kyc

import (
	"bytes"
	"context"
	"errors"
	"image"
	"image/color"
	stdjpeg "image/jpeg"
	"io"
	"log/slog"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"shiptrip/pkg/auth"
)

const testSecret = "test-secret-do-not-use-in-prod"

func discardLogger() *slog.Logger { return slog.New(slog.NewTextHandler(io.Discard, nil)) }

func testValidator(t *testing.T) *auth.Validator {
	t.Helper()
	v, err := auth.NewValidator(testSecret, discardLogger())
	if err != nil {
		t.Fatalf("NewValidator: %v", err)
	}
	return v
}

// accessToken mints a valid access JWT for userID.
func accessToken(t *testing.T, userID int64) string {
	t.Helper()
	claims := auth.Claims{
		UserID: userID,
		Role:   "sender",
		Type:   "access",
		RegisteredClaims: jwt.RegisteredClaims{
			IssuedAt:  jwt.NewNumericDate(time.Now()),
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(5 * time.Minute)),
			ID:        "jti-test",
		},
	}
	tok, err := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(testSecret))
	if err != nil {
		t.Fatalf("sign: %v", err)
	}
	return tok
}

// ── stubs ───────────────────────────────────────────────────────────────────────

type putCall struct{ bucket, key string }

// fakeStore records Put/Delete and can fail a chosen field's Put. Records
// the order of keys so orphan-cleanup assertions can check what was deleted.
type fakeStore struct {
	mu        sync.Mutex
	puts      []putCall
	deletes   []string
	failOnKey string // substring; Put returns an error if key contains it
}

func (f *fakeStore) Put(_ context.Context, bucket, key string, body io.Reader, _ string) error {
	// Drain the body so the multipart reader behaves like the real path.
	_, _ = io.Copy(io.Discard, body)
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.failOnKey != "" && strings.Contains(key, f.failOnKey) {
		return errors.New("simulated s3 put failure")
	}
	f.puts = append(f.puts, putCall{bucket, key})
	return nil
}

func (f *fakeStore) Delete(_ context.Context, _ string, key string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.deletes = append(f.deletes, key)
	return nil
}

func (f *fakeStore) putKeys() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := make([]string, len(f.puts))
	for i, p := range f.puts {
		out[i] = p.key
	}
	return out
}

func (f *fakeStore) deletedKeys() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := make([]string, len(f.deletes))
	copy(out, f.deletes)
	return out
}

// stubRecorder returns a configured output/error and records the input.
type stubRecorder struct {
	out    RecordSubmissionOutput
	err    error
	mu     sync.Mutex
	called bool
	gotIn  RecordSubmissionInput
}

type stubLimiter struct {
	mu         sync.Mutex
	remaining  int
	retryAfter time.Duration
	err        error
	calls      int
}

func (s *stubLimiter) Allow(_ context.Context, _ int64, _ string) (UploadRateLimitDecision, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls++
	if s.err != nil {
		return UploadRateLimitDecision{}, s.err
	}
	if s.remaining <= 0 {
		return UploadRateLimitDecision{Allowed: false, RetryAfter: s.retryAfter}, nil
	}
	s.remaining--
	return UploadRateLimitDecision{Allowed: true}, nil
}

func allowLimiter() *stubLimiter { return &stubLimiter{remaining: 1_000} }

func (s *stubRecorder) RecordSubmission(_ context.Context, in RecordSubmissionInput) (RecordSubmissionOutput, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.called = true
	s.gotIn = in
	return s.out, s.err
}

func newHandler(store objectStore, rec Recorder) *Handler {
	return &Handler{
		Validator: nil, // set per-test where auth matters
		Limiter:   allowLimiter(),
		Storage:   store,
		Bucket:    "kyc-docs",
		Recorder:  rec,
		Log:       discardLogger(),
	}
}

// ── request builder ──────────────────────────────────────────────────────────────

const validIdemKey = "0123456789abcdef0123456789abcdef" // 32 hex

type imagePart struct {
	field       string
	filename    string
	contentType string
	data        []byte
}

func multipartReq(t *testing.T, token, docType, idemKey string, parts []imagePart) *http.Request {
	t.Helper()
	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	if docType != "" {
		_ = w.WriteField(fieldDocumentType, docType)
	}
	if idemKey != "" {
		_ = w.WriteField(fieldIdempotencyKey, idemKey)
	}
	for _, p := range parts {
		hdr := make(map[string][]string)
		hdr["Content-Disposition"] = []string{`form-data; name="` + p.field + `"; filename="` + p.filename + `"`}
		hdr["Content-Type"] = []string{p.contentType}
		fw, err := w.CreatePart(hdr)
		if err != nil {
			t.Fatalf("CreatePart: %v", err)
		}
		if _, err := fw.Write(p.data); err != nil {
			t.Fatalf("write part: %v", err)
		}
	}
	if err := w.Close(); err != nil {
		t.Fatalf("close writer: %v", err)
	}
	req := httptest.NewRequest(http.MethodPost, "/kyc/submit", &buf)
	req.Header.Set("Content-Type", w.FormDataContentType())
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	return req
}

// jpeg builds a small, decodable JPEG part for the given field. The handler
// validates both the signature and decoded image configuration, so test data
// must be a real image rather than bytes with a JPEG Content-Type label.
func jpeg(field string, n int) imagePart {
	width := n
	if width < 1 {
		width = 1
	}
	img := image.NewRGBA(image.Rect(0, 0, width, 1))
	for x := 0; x < width; x++ {
		img.Set(x, 0, color.RGBA{R: byte(x), G: 80, B: 120, A: 255})
	}
	var buf bytes.Buffer
	if err := stdjpeg.Encode(&buf, img, &stdjpeg.Options{Quality: 75}); err != nil {
		panic(err)
	}
	data := buf.Bytes()
	if n == 0 {
		data = nil
	}
	return imagePart{field: field, filename: field + ".jpg", contentType: "image/jpeg", data: data}
}

// truncatedJPEG keeps enough of a real JPEG for DecodeConfig to accept its
// header while removing pixel data that a full decode must reject.
func truncatedJPEG(field string) imagePart {
	part := jpeg(field, 100)
	for cut := len(part.data) - 1; cut > 0; cut-- {
		candidate := part.data[:cut]
		if _, _, err := image.DecodeConfig(bytes.NewReader(candidate)); err != nil {
			continue
		}
		if _, _, err := image.Decode(bytes.NewReader(candidate)); err != nil {
			part.data = candidate
			return part
		}
	}
	panic("could not construct a header-valid truncated JPEG")
}

func idCardParts() []imagePart {
	return []imagePart{jpeg(fieldFront, 100), jpeg(fieldBack, 100), jpeg(fieldSelfie, 100)}
}

// ── tests ────────────────────────────────────────────────────────────────────────

func TestSubmit_HappyPathCreated(t *testing.T) {
	store := &fakeStore{}
	rec := &stubRecorder{out: RecordSubmissionOutput{SubmissionID: 7, Created: true, Status: StatusPending}}
	h := newHandler(store, rec)
	h.Validator = testValidator(t)

	req := multipartReq(t, accessToken(t, 42), string(DocumentIDCard), validIdemKey, idCardParts())
	rr := httptest.NewRecorder()
	h.handleSubmit(rr, req)

	if rr.Code != http.StatusCreated {
		t.Fatalf("status = %d, want 201; body=%s", rr.Code, rr.Body.String())
	}
	if !rec.called {
		t.Error("RecordSubmission was not called")
	}
	// Three deterministic keys uploaded under the user's prefix.
	keys := store.putKeys()
	if len(keys) != 3 {
		t.Fatalf("uploaded %d keys, want 3: %v", len(keys), keys)
	}
	// Keys are relative to the bucket — `<uid>/<idem>-<field>.<ext>`, with NO
	// leading `kyc-docs/` (the bucket name is not repeated in the object key).
	for _, k := range keys {
		if !strings.HasPrefix(k, "42/"+validIdemKey+"-") {
			t.Errorf("key %q lacks deterministic prefix %q", k, "42/"+validIdemKey+"-")
		}
		if strings.HasPrefix(k, "kyc-docs/") {
			t.Errorf("key %q repeats the bucket name; want bucket-relative path", k)
		}
	}
	// Success → no orphan cleanup.
	if d := store.deletedKeys(); len(d) != 0 {
		t.Errorf("deleted %v on success, want none", d)
	}
	// Recorder got the keys we uploaded.
	if rec.gotIn.FrontImageKey == "" || rec.gotIn.SelfieImageKey == "" {
		t.Errorf("recorder input missing keys: %+v", rec.gotIn)
	}
}

func TestSubmit_ExistingReturns200(t *testing.T) {
	store := &fakeStore{}
	rec := &stubRecorder{out: RecordSubmissionOutput{SubmissionID: 7, Created: false, Status: StatusPending}}
	h := newHandler(store, rec)
	h.Validator = testValidator(t)

	req := multipartReq(t, accessToken(t, 42), string(DocumentIDCard), validIdemKey, idCardParts())
	rr := httptest.NewRecorder()
	h.handleSubmit(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (idempotent replay); body=%s", rr.Code, rr.Body.String())
	}
}

func TestSubmit_PassportNeedsNoBack(t *testing.T) {
	store := &fakeStore{}
	rec := &stubRecorder{out: RecordSubmissionOutput{SubmissionID: 1, Created: true, Status: StatusPending}}
	h := newHandler(store, rec)
	h.Validator = testValidator(t)

	// Passport: front + selfie only, no back part.
	parts := []imagePart{jpeg(fieldFront, 100), jpeg(fieldSelfie, 100)}
	req := multipartReq(t, accessToken(t, 42), string(DocumentPassport), validIdemKey, parts)
	rr := httptest.NewRecorder()
	h.handleSubmit(rr, req)

	if rr.Code != http.StatusCreated {
		t.Fatalf("status = %d, want 201; body=%s", rr.Code, rr.Body.String())
	}
	if keys := store.putKeys(); len(keys) != 2 {
		t.Errorf("uploaded %d keys, want 2 (no back): %v", len(keys), keys)
	}
	if rec.gotIn.BackImageKey != "" {
		t.Errorf("back key = %q, want empty for passport", rec.gotIn.BackImageKey)
	}
}

func TestSubmit_Unauthorized(t *testing.T) {
	h := newHandler(&fakeStore{}, &stubRecorder{})
	h.Validator = testValidator(t)
	limiter := &stubLimiter{remaining: 1}
	h.Limiter = limiter

	// No Authorization header.
	req := multipartReq(t, "", string(DocumentIDCard), validIdemKey, idCardParts())
	rr := httptest.NewRecorder()
	h.handleSubmit(rr, req)

	if rr.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401", rr.Code)
	}
	if limiter.calls != 0 {
		t.Fatalf("limiter called %d times before authentication, want 0", limiter.calls)
	}
}

func TestSubmit_RepeatedUploadsEventually429WithRetryAfter(t *testing.T) {
	store := &fakeStore{}
	rec := &stubRecorder{out: RecordSubmissionOutput{SubmissionID: 7, Created: true, Status: StatusPending}}
	h := newHandler(store, rec)
	h.Validator = testValidator(t)
	h.Limiter = &stubLimiter{remaining: 2, retryAfter: 90*time.Second + time.Millisecond}

	for attempt, want := range []int{http.StatusCreated, http.StatusCreated, http.StatusTooManyRequests} {
		req := multipartReq(t, accessToken(t, 42), string(DocumentIDCard), validIdemKey, idCardParts())
		rr := httptest.NewRecorder()
		h.handleSubmit(rr, req)
		if rr.Code != want {
			t.Fatalf("attempt %d status = %d, want %d; body=%s", attempt+1, rr.Code, want, rr.Body.String())
		}
		if want == http.StatusTooManyRequests {
			if got := rr.Header().Get("Retry-After"); got != "91" {
				t.Fatalf("Retry-After = %q, want 91", got)
			}
			body := rr.Body.String()
			if !strings.Contains(body, `"code":"kyc_upload_rate_limited"`) {
				t.Fatalf("429 body lacks safe code: %s", body)
			}
			for _, secret := range []string{"redis", "127.0.0.1", validIdemKey} {
				if strings.Contains(strings.ToLower(body), strings.ToLower(secret)) {
					t.Fatalf("429 body leaked %q: %s", secret, body)
				}
			}
		}
	}
}

func TestSubmit_RateLimiterFailureFailsClosedWithoutInternalDetails(t *testing.T) {
	store := &fakeStore{}
	rec := &stubRecorder{}
	h := newHandler(store, rec)
	h.Validator = testValidator(t)
	h.Limiter = &stubLimiter{err: errors.New("dial redis://secret@cache.internal:6379: connection refused")}

	req := multipartReq(t, accessToken(t, 42), string(DocumentIDCard), validIdemKey, idCardParts())
	rr := httptest.NewRecorder()
	h.handleSubmit(rr, req)

	if rr.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503; body=%s", rr.Code, rr.Body.String())
	}
	body := rr.Body.String()
	if !strings.Contains(body, `"code":"kyc_upload_rate_limit_unavailable"`) {
		t.Fatalf("503 body lacks safe code: %s", body)
	}
	for _, secret := range []string{"redis", "secret", "cache.internal", validIdemKey} {
		if strings.Contains(strings.ToLower(body), strings.ToLower(secret)) {
			t.Fatalf("503 body leaked %q: %s", secret, body)
		}
	}
	if len(store.putKeys()) != 0 || rec.called {
		t.Fatal("fail-closed limiter failure reached storage or recorder")
	}
}

func TestSubmit_MissingRateLimiterFailsClosed(t *testing.T) {
	h := newHandler(&fakeStore{}, &stubRecorder{})
	h.Validator = testValidator(t)
	h.Limiter = nil
	req := multipartReq(t, accessToken(t, 42), string(DocumentIDCard), validIdemKey, idCardParts())
	rr := httptest.NewRecorder()
	h.handleSubmit(rr, req)
	if rr.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503; body=%s", rr.Code, rr.Body.String())
	}
}

func TestSubmit_RejectsBadInputs(t *testing.T) {
	cases := []struct {
		name    string
		docType string
		idemKey string
		parts   []imagePart
		want    int
	}{
		{"bad document_type", "bogus", validIdemKey, idCardParts(), http.StatusBadRequest},
		{"missing document_type", "", validIdemKey, idCardParts(), http.StatusBadRequest},
		{"short idempotency_key", string(DocumentIDCard), "abc", idCardParts(), http.StatusBadRequest},
		{"non-hex idempotency_key", string(DocumentIDCard), strings.Repeat("z", 32), idCardParts(), http.StatusBadRequest},
		{"missing front", string(DocumentIDCard), validIdemKey, []imagePart{jpeg(fieldBack, 100), jpeg(fieldSelfie, 100)}, http.StatusBadRequest},
		{"missing back for id_card", string(DocumentIDCard), validIdemKey, []imagePart{jpeg(fieldFront, 100), jpeg(fieldSelfie, 100)}, http.StatusBadRequest},
		{"missing selfie", string(DocumentIDCard), validIdemKey, []imagePart{jpeg(fieldFront, 100), jpeg(fieldBack, 100)}, http.StatusBadRequest},
		{"bad content type", string(DocumentIDCard), validIdemKey, []imagePart{
			{field: fieldFront, filename: "f.gif", contentType: "image/gif", data: []byte{1, 2, 3}},
			jpeg(fieldBack, 100), jpeg(fieldSelfie, 100),
		}, http.StatusUnsupportedMediaType},
		{"declared jpeg with invalid content", string(DocumentIDCard), validIdemKey, []imagePart{
			{field: fieldFront, filename: "f.jpg", contentType: "image/jpeg", data: []byte("not an image")},
			jpeg(fieldBack, 100), jpeg(fieldSelfie, 100),
		}, http.StatusUnsupportedMediaType},
		{"header-valid truncated jpeg", string(DocumentIDCard), validIdemKey, []imagePart{
			truncatedJPEG(fieldFront), jpeg(fieldBack, 100), jpeg(fieldSelfie, 100),
		}, http.StatusUnsupportedMediaType},
		{"empty front file", string(DocumentIDCard), validIdemKey, []imagePart{
			jpeg(fieldFront, 0), jpeg(fieldBack, 100), jpeg(fieldSelfie, 100),
		}, http.StatusRequestEntityTooLarge},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			store := &fakeStore{}
			rec := &stubRecorder{}
			h := newHandler(store, rec)
			h.Validator = testValidator(t)

			req := multipartReq(t, accessToken(t, 42), tc.docType, tc.idemKey, tc.parts)
			rr := httptest.NewRecorder()
			h.handleSubmit(rr, req)

			if rr.Code != tc.want {
				t.Fatalf("status = %d, want %d; body=%s", rr.Code, tc.want, rr.Body.String())
			}
			// A rejected request must never call the recorder.
			if rec.called {
				t.Error("RecordSubmission was called on a rejected request")
			}
		})
	}
}

func TestSubmit_RecorderNotConfiguredReturns503(t *testing.T) {
	store := &fakeStore{}
	h := newHandler(store, NoopRecorder{})
	h.Validator = testValidator(t)

	req := multipartReq(t, accessToken(t, 42), string(DocumentIDCard), validIdemKey, idCardParts())
	rr := httptest.NewRecorder()
	h.handleSubmit(rr, req)

	if rr.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", rr.Code)
	}
	// Images uploaded before the failed record must be cleaned up.
	if d := store.deletedKeys(); len(d) != 3 {
		t.Errorf("orphan cleanup deleted %d keys, want 3: %v", len(d), d)
	}
}

func TestSubmit_RecorderErrorReturns502AndCleansUp(t *testing.T) {
	store := &fakeStore{}
	rec := &stubRecorder{err: errors.New("django gRPC unreachable")}
	h := newHandler(store, rec)
	h.Validator = testValidator(t)

	req := multipartReq(t, accessToken(t, 42), string(DocumentIDCard), validIdemKey, idCardParts())
	rr := httptest.NewRecorder()
	h.handleSubmit(rr, req)

	if rr.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502; body=%s", rr.Code, rr.Body.String())
	}
	if d := store.deletedKeys(); len(d) != 3 {
		t.Errorf("orphan cleanup deleted %d keys, want 3 (all uploaded): %v", len(d), d)
	}
}

func TestSubmit_PartialUploadFailureCleansEarlierUploads(t *testing.T) {
	// front lands, selfie Put fails → the already-uploaded front must be
	// cleaned up, and the recorder must never be called.
	store := &fakeStore{failOnKey: "-selfie"}
	rec := &stubRecorder{}
	h := newHandler(store, rec)
	h.Validator = testValidator(t)

	req := multipartReq(t, accessToken(t, 42), string(DocumentIDCard), validIdemKey, idCardParts())
	rr := httptest.NewRecorder()
	h.handleSubmit(rr, req)

	if rr.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want 500 (upload failed); body=%s", rr.Code, rr.Body.String())
	}
	if rec.called {
		t.Error("RecordSubmission must not be called when an upload failed")
	}
	// front + back uploaded before selfie failed → both cleaned up.
	if d := store.deletedKeys(); len(d) != 2 {
		t.Errorf("cleanup deleted %d keys, want 2 (front+back): %v", len(d), d)
	}
}

func TestSubmit_TooManyPartsForOneField(t *testing.T) {
	store := &fakeStore{}
	rec := &stubRecorder{}
	h := newHandler(store, rec)
	h.Validator = testValidator(t)

	// Two front parts → handler rejects.
	parts := []imagePart{jpeg(fieldFront, 100), jpeg(fieldFront, 100), jpeg(fieldBack, 100), jpeg(fieldSelfie, 100)}
	req := multipartReq(t, accessToken(t, 42), string(DocumentIDCard), validIdemKey, parts)
	rr := httptest.NewRecorder()
	h.handleSubmit(rr, req)

	if rr.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400 (too many parts); body=%s", rr.Code, rr.Body.String())
	}
	if rec.called {
		t.Error("RecordSubmission called despite too-many-parts rejection")
	}
}
