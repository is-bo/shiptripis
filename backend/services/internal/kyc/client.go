// Package kyc implements the Go KYC service: HTTP entry from Flutter,
// MinIO/S3 upload, gRPC handoff to Django for the authoritative row.
//
// gRPC client is hand-written as an interface here so the rest of the
// service compiles before the generated stubs land. Once
// contracts/grpc/kyc.proto is wired into `task contract:generate-grpc`,
// replace recorder with the generated `kycpb.KYCSubmissionServiceClient`.
package kyc

import (
	"context"
	"errors"
)

// DocumentType mirrors kyc.proto. Values are the wire-format strings the
// kyc-service accepts from Flutter; the proto-generated enum maps each
// to its uppercase form when the real client lands.
type DocumentType string

const (
	DocumentIDCard         DocumentType = "id_card"
	DocumentPassport       DocumentType = "passport"
	DocumentDrivingLicense DocumentType = "driving_license"
)

// Status mirrors kyc.proto Status. Returned by RecordSubmission.
type Status string

const (
	StatusPending  Status = "pending"
	StatusApproved Status = "approved"
	StatusRejected Status = "rejected"
	StatusExpired  Status = "expired"
)

// RecordSubmissionInput is the metadata sent to Django after the images
// are durably in MinIO. The kyc-service generates nothing here itself —
// every field originates with Flutter or with this service's S3 upload
// result.
type RecordSubmissionInput struct {
	UserID         int64
	DocumentType   DocumentType
	IdempotencyKey string
	FrontImageKey  string
	BackImageKey   string
	SelfieImageKey string
}

// RecordSubmissionOutput is what Django returns. Created==false means the
// row already existed under the same idempotency_key — the HTTP layer
// returns 200 instead of 201 in that case.
type RecordSubmissionOutput struct {
	SubmissionID int64
	Created      bool
	Status       Status
}

// Recorder is the gRPC client surface. The real implementation will be
// the generated stub wrapped to translate proto enums ↔ these typed
// strings. Until codegen lands the wiring uses NoopRecorder, which
// fails loudly so a half-built deploy is impossible to miss.
type Recorder interface {
	RecordSubmission(ctx context.Context, in RecordSubmissionInput) (RecordSubmissionOutput, error)
}

// ErrRecorderNotConfigured is returned by NoopRecorder so callers can
// distinguish "Django gRPC unreachable" from "we never wired it".
var ErrRecorderNotConfigured = errors.New("kyc: gRPC recorder not configured")

// NoopRecorder is the placeholder until the gRPC client lands. It always
// fails so an accidental production deploy of a half-built service is
// loud, not silent.
type NoopRecorder struct{}

func (NoopRecorder) RecordSubmission(_ context.Context, _ RecordSubmissionInput) (RecordSubmissionOutput, error) {
	return RecordSubmissionOutput{}, ErrRecorderNotConfigured
}
