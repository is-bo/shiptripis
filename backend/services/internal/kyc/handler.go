package kyc

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"image"
	_ "image/jpeg"
	_ "image/png"
	"io"
	"log/slog"
	"mime/multipart"
	"net/http"
	"path"
	"strings"
	"time"

	"shiptrip/pkg/auth"
)

// MaxImageBytes caps each uploaded image. Per ARCHITECTURE.md §11 the
// client enforces a similar cap; this is the server-side backstop. A
// passport scan from a modern phone is rarely over 4 MB; reject anything
// claiming much more.
const MaxImageBytes int64 = 8 << 20 // 8 MiB

// MaxImagePixels prevents a small, maliciously crafted image header from
// making a later reviewer/thumbnailer allocate an unreasonable decoded image.
// 48 MP comfortably covers modern phone cameras used for identity documents.
const MaxImagePixels int64 = 48_000_000

// MaxMultipartMemory bounds how much of the multipart body sits in RAM
// before spilling to a temp file. Each upload uses two or three image
// parts; 16 MiB covers most without touching disk.
const MaxMultipartMemory int64 = 16 << 20

// MaxRequestBytes is the hard cap on the whole multipart body. Three
// images at MaxImageBytes (8 MiB) + form fields → 25 MiB leaves a
// little headroom without letting a hostile client tie up a goroutine
// streaming forever.
const MaxRequestBytes int64 = 25 << 20

// recordSubmissionTimeout bounds the gRPC handoff to Django. Comfortably
// covers the SDK's own retry policy (4 attempts × ≤2s backoff = ~6s
// worst case) with headroom for slow networks.
const recordSubmissionTimeout = 10 * time.Second

// SubmissionFormFields are the multipart form field names Flutter sends.
const (
	fieldDocumentType   = "document_type"
	fieldIdempotencyKey = "idempotency_key"
	fieldFront          = "front"
	fieldBack           = "back"
	fieldSelfie         = "selfie"
)

// allowedDocumentTypes is the closed set the wire format accepts. Kept
// in lockstep with kyc.proto DocumentType + Django KycSubmission.DocumentType.
var allowedDocumentTypes = map[DocumentType]struct{}{
	DocumentIDCard:         {},
	DocumentPassport:       {},
	DocumentDrivingLicense: {},
}

// allowedContentTypes are the image MIME types we accept. JPEG + PNG
// cover what mobile cameras emit; HEIC is converted to JPEG by Flutter
// before upload (mobile rule, not server-enforced).
var allowedContentTypes = map[string]string{
	"image/jpeg": ".jpg",
	"image/png":  ".png",
}

var allowedImageFormats = map[string]string{
	"image/jpeg": "jpeg",
	"image/png":  "png",
}

// objectStore is the subset of *storage.Client the handler needs. Narrowed
// to an interface so unit tests can inject a fake without a live MinIO/S3 —
// *storage.Client satisfies it unchanged, so production wiring is identical.
type objectStore interface {
	Put(ctx context.Context, bucket, key string, body io.Reader, contentType string) error
	Delete(ctx context.Context, bucket, key string) error
}

// Handler bundles the HTTP-side dependencies. The auth validator turns
// the bearer token into a user_id; the storage client owns the MinIO
// uploads; the recorder is the gRPC client to Django.
type Handler struct {
	Validator      *auth.Validator
	Limiter        UploadRateLimiter
	ClientIPSource ClientIPSource
	Storage        objectStore
	Bucket         string
	Recorder       Recorder
	Log            *slog.Logger
}

// Mount installs the KYC routes on the given mux. Caddy strips
// `/api/v1` before forwarding, so the routes here are unversioned.
func (h *Handler) Mount(mux *http.ServeMux) {
	mux.HandleFunc("POST /kyc/submit", h.handleSubmit)
}

type submissionResponse struct {
	SubmissionID int64  `json:"submission_id"`
	Status       Status `json:"status"`
	Created      bool   `json:"created"`
}

type errorResponse struct {
	Error  string `json:"error"`
	Code   string `json:"code,omitempty"`
	Detail string `json:"detail,omitempty"`
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, errorResponse{Error: msg})
}

func writeStructuredError(w http.ResponseWriter, status int, code, detail string) {
	writeJSON(w, status, errorResponse{Error: detail, Code: code, Detail: detail})
}

func (h *Handler) handleSubmit(w http.ResponseWriter, r *http.Request) {
	claims, err := h.authenticate(r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	if h.Limiter == nil {
		// A missing limiter is a service wiring defect. KYC upload is
		// storage-sensitive, so fail closed instead of silently restoring the
		// pre-Phase-7A unlimited path.
		h.Log.Error("kyc: upload rate limiter not configured", "user_id", claims.UserID)
		writeStructuredError(
			w,
			http.StatusServiceUnavailable,
			"kyc_upload_rate_limit_unavailable",
			"KYC uploads are temporarily unavailable. Try again later.",
		)
		return
	}
	limitDecision, err := h.Limiter.Allow(
		r.Context(),
		claims.UserID,
		requestClientIP(r, h.ClientIPSource),
	)
	if err != nil {
		// Redis is transient abuse-control state, not KYC authority. Refuse
		// storage work until the shared budget is available; do not leak the
		// Redis address/error to the client.
		h.Log.Error("kyc: upload rate limiter unavailable", "err", err, "user_id", claims.UserID)
		writeStructuredError(
			w,
			http.StatusServiceUnavailable,
			"kyc_upload_rate_limit_unavailable",
			"KYC uploads are temporarily unavailable. Try again later.",
		)
		return
	}
	if !limitDecision.Allowed {
		retrySeconds := int64((limitDecision.RetryAfter + time.Second - 1) / time.Second)
		if retrySeconds < 1 {
			retrySeconds = 1
		}
		w.Header().Set("Retry-After", fmt.Sprintf("%d", retrySeconds))
		writeStructuredError(
			w,
			http.StatusTooManyRequests,
			"kyc_upload_rate_limited",
			"Too many KYC upload attempts. Try again later.",
		)
		return
	}

	r.Body = http.MaxBytesReader(w, r.Body, MaxRequestBytes)
	if err := r.ParseMultipartForm(MaxMultipartMemory); err != nil {
		writeError(w, http.StatusBadRequest, "invalid multipart body")
		return
	}
	defer func() { _ = r.MultipartForm.RemoveAll() }()

	docTypeRaw := strings.TrimSpace(r.FormValue(fieldDocumentType))
	if _, ok := allowedDocumentTypes[DocumentType(docTypeRaw)]; !ok {
		writeError(w, http.StatusBadRequest, "invalid document_type")
		return
	}
	docType := DocumentType(docTypeRaw)

	idemKey := strings.TrimSpace(r.FormValue(fieldIdempotencyKey))
	if !isValidIdempotencyKey(idemKey) {
		writeError(w, http.StatusBadRequest, "invalid idempotency_key")
		return
	}

	// Track every key we successfully PUT so a later failure cleans up
	// all of them, not just the last batch. Deferred cleanup runs unless
	// success is flipped to true after the Recorder call returns OK —
	// covers partial-upload failures (back/selfie fail after front lands)
	// in addition to the post-RecordSubmission case.
	var (
		uploaded []string
		success  bool
	)
	defer func() {
		if success || len(uploaded) == 0 {
			return
		}
		h.cleanupOrphans(claims.UserID, uploaded...)
	}()

	// Front image is always required; back is required for ID and
	// driving licence; selfie is always required for liveness.
	frontKey, err := h.uploadImage(r.Context(), claims.UserID, idemKey, r.MultipartForm, fieldFront, true)
	if err != nil {
		writeUploadError(w, fieldFront, err)
		return
	}
	if frontKey != "" {
		uploaded = append(uploaded, frontKey)
	}
	backKey, err := h.uploadImage(r.Context(), claims.UserID, idemKey, r.MultipartForm, fieldBack, docType != DocumentPassport)
	if err != nil {
		writeUploadError(w, fieldBack, err)
		return
	}
	if backKey != "" {
		uploaded = append(uploaded, backKey)
	}
	selfieKey, err := h.uploadImage(r.Context(), claims.UserID, idemKey, r.MultipartForm, fieldSelfie, true)
	if err != nil {
		writeUploadError(w, fieldSelfie, err)
		return
	}
	if selfieKey != "" {
		uploaded = append(uploaded, selfieKey)
	}

	// Bounded deadline on the gRPC handoff so a hung Django doesn't tie
	// up an HTTP goroutine until the global ReadTimeout. The deadline
	// also fences in the SDK's own retry policy (4 attempts × 2s backoff).
	rpcCtx, rpcCancel := context.WithTimeout(r.Context(), recordSubmissionTimeout)
	defer rpcCancel()

	out, err := h.Recorder.RecordSubmission(rpcCtx, RecordSubmissionInput{
		UserID:         claims.UserID,
		DocumentType:   docType,
		IdempotencyKey: idemKey,
		FrontImageKey:  frontKey,
		BackImageKey:   backKey,
		SelfieImageKey: selfieKey,
	})
	if err != nil {
		// Image bytes are already in S3. Deferred cleanup above handles
		// the orphan delete; the idempotency_key still protects against
		// double-recording on the client's retry.
		if errors.Is(err, ErrRecorderNotConfigured) {
			// Loud signal during partial-build deploys.
			h.Log.Error("kyc: recorder not configured",
				"user_id", claims.UserID,
			)
			writeError(w, http.StatusServiceUnavailable, "kyc backend unavailable")
			return
		}
		h.Log.Error("kyc: RecordSubmission failed",
			"err", err, "user_id", claims.UserID)
		writeError(w, http.StatusBadGateway, "kyc backend error")
		return
	}

	success = true
	status := http.StatusOK
	if out.Created {
		status = http.StatusCreated
	}
	writeJSON(w, status, submissionResponse{
		SubmissionID: out.SubmissionID,
		Status:       out.Status,
		Created:      out.Created,
	})
}

func (h *Handler) authenticate(r *http.Request) (*auth.Claims, error) {
	header := r.Header.Get("Authorization")
	const prefix = "Bearer "
	if len(header) < len(prefix) || !strings.EqualFold(header[:len(prefix)], prefix) {
		return nil, errors.New("missing bearer token")
	}
	tok := strings.TrimSpace(header[len(prefix):])
	if tok == "" {
		return nil, errors.New("empty bearer token")
	}
	return h.Validator.Validate(tok)
}

// uploadImage reads one multipart file part, validates type + size, and
// streams it to S3 at key `<user_id>/<idempotency_key>-<field>.<ext>` inside
// the kyc-docs bucket. The key is deterministic in (user, idempotency_key,
// field) so retries overwrite rather than orphan. Returns the S3 key, or ""
// if the part is absent and !required.
func (h *Handler) uploadImage(
	ctx context.Context,
	userID int64,
	idemKey string,
	form *multipart.Form,
	field string,
	required bool,
) (string, error) {
	files := form.File[field]
	if len(files) == 0 {
		if required {
			return "", errMissing
		}
		return "", nil
	}
	if len(files) > 1 {
		return "", errTooMany
	}
	header := files[0]
	if header.Size <= 0 || header.Size > MaxImageBytes {
		return "", errBadSize
	}
	contentType := header.Header.Get("Content-Type")
	ext, ok := allowedContentTypes[contentType]
	if !ok {
		return "", errBadType
	}

	f, err := header.Open()
	if err != nil {
		return "", fmt.Errorf("open part: %w", err)
	}
	defer func() { _ = f.Close() }()
	if err := validateImageContent(f, contentType); err != nil {
		return "", err
	}

	key := imageKey(userID, idemKey, field, ext)
	// storage.Put enforces its own overflow cap (see pkg/storage/s3.go).
	if err := h.Storage.Put(ctx, h.Bucket, key, f, contentType); err != nil {
		return "", fmt.Errorf("s3 put: %w", err)
	}
	return key, nil
}

func validateImageContent(f multipart.File, declaredContentType string) error {
	var sniff [512]byte
	n, err := f.Read(sniff[:])
	if err != nil && !errors.Is(err, io.EOF) {
		return fmt.Errorf("read image signature: %w", err)
	}
	if http.DetectContentType(sniff[:n]) != declaredContentType {
		return errBadContent
	}
	if _, err := f.Seek(0, io.SeekStart); err != nil {
		return fmt.Errorf("reset image after signature: %w", err)
	}
	decoded, format, err := image.DecodeConfig(f)
	if err != nil || format != allowedImageFormats[declaredContentType] {
		return errBadContent
	}
	if decoded.Width <= 0 || decoded.Height <= 0 || int64(decoded.Width)*int64(decoded.Height) > MaxImagePixels {
		return errBadContent
	}
	if _, err := f.Seek(0, io.SeekStart); err != nil {
		return fmt.Errorf("reset image before full validation: %w", err)
	}
	fullyDecoded, fullFormat, err := image.Decode(f)
	if err != nil || fullFormat != allowedImageFormats[declaredContentType] {
		return errBadContent
	}
	fullBounds := fullyDecoded.Bounds()
	if fullBounds.Dx() != decoded.Width || fullBounds.Dy() != decoded.Height {
		return errBadContent
	}
	if _, err := f.Seek(0, io.SeekStart); err != nil {
		return fmt.Errorf("reset image after validation: %w", err)
	}
	return nil
}

// cleanupOrphans best-effort deletes images after a failed RecordSubmission.
// Detached context so a cancelled request still completes the cleanup; we
// don't surface the deletion error to the client either way.
func (h *Handler) cleanupOrphans(userID int64, keys ...string) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	for _, key := range keys {
		if key == "" {
			continue
		}
		if err := h.Storage.Delete(ctx, h.Bucket, key); err != nil {
			h.Log.Warn("kyc: orphan cleanup failed",
				"user_id", userID, "err", err)
		}
	}
}

var (
	errMissing    = errors.New("missing")
	errTooMany    = errors.New("too many parts")
	errBadSize    = errors.New("bad size")
	errBadType    = errors.New("bad content type")
	errBadContent = errors.New("invalid image content")
)

func writeUploadError(w http.ResponseWriter, field string, err error) {
	switch {
	case errors.Is(err, errMissing):
		writeError(w, http.StatusBadRequest, field+": required")
	case errors.Is(err, errTooMany):
		writeError(w, http.StatusBadRequest, field+": too many parts")
	case errors.Is(err, errBadSize):
		writeError(w, http.StatusRequestEntityTooLarge, field+": invalid size")
	case errors.Is(err, errBadType):
		writeError(w, http.StatusUnsupportedMediaType, field+": unsupported content type")
	case errors.Is(err, errBadContent):
		writeError(w, http.StatusUnsupportedMediaType, field+": invalid image content")
	default:
		writeError(w, http.StatusInternalServerError, field+": upload failed")
	}
}

// imageKey builds the S3 object path deterministically. Retries with the
// same idempotency_key overwrite rather than orphan; Django dedupes the
// row on idempotency_key, so the second upload's keys reuse the first
// row and the bytes are simply the latest attempt.
//
// The key is relative to the bucket (h.Bucket, "kyc-docs") and must NOT
// repeat the bucket name — doing so produced the legacy doubled
// `kyc-docs/kyc-docs/<uid>/…` path. Objects now land at
// `<user_id>/<idempotency_key>-<field>.<ext>`. NOTE: this changed the
// stored-key shape — existing kyc_submission rows + MinIO objects from
// before this fix reference the old doubled path and need a one-time
// migration (see HANDOVER.md "imageKey prefix fix").
func imageKey(userID int64, idemKey, field, ext string) string {
	return path.Join(fmt.Sprintf("%d", userID), idemKey+"-"+field+ext)
}

// isValidIdempotencyKey accepts 32-char hex (Flutter sends UUID v4 hex,
// no dashes). Tight on purpose — anything else is a client bug we want
// surfaced loudly rather than silently rewritten.
func isValidIdempotencyKey(s string) bool {
	if len(s) != 32 {
		return false
	}
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch {
		case c >= '0' && c <= '9':
		case c >= 'a' && c <= 'f':
		default:
			return false
		}
	}
	return true
}
