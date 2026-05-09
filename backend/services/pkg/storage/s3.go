// Package storage provides an S3-compatible object-storage client.
//
// Per CLAUDE.md G4: all object storage access goes through this package
// using aws-sdk-go-v2 against a custom endpoint. MinIO is the dev
// endpoint; production runs against Backblaze B2 or Hetzner Object
// Storage. Provider-specific admin APIs (bucket creation, lifecycle
// policies, etc.) MUST NOT live in app code — they belong in infra.
//
// Date-semantics differences between providers (notably presigned-URL
// signature time tolerance) are why presigned flows must be tested
// against the actual prod provider in staging, not just MinIO.
package storage

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/aws/smithy-go"
)

// ErrNotFound is returned by Head/Get/Delete when the object does not
// exist. Wrap-aware: use errors.Is(err, ErrNotFound).
var ErrNotFound = errors.New("storage: object not found")

// Config holds the connection parameters. Endpoint is required for
// MinIO and most non-AWS providers; leave it empty only for real AWS S3.
type Config struct {
	Endpoint  string // e.g. "http://minio:9000" — empty for real AWS
	Region    string // S3 region; "us-east-1" is a safe default for MinIO
	AccessKey string
	SecretKey string

	// UsePathStyle forces path-style addressing (bucket in URL path,
	// not virtual-host). MinIO requires this; most production S3-compat
	// providers also accept it. Default true if Endpoint is set.
	UsePathStyle bool

	Logger *slog.Logger

	// MaxPutBytes caps Put() body size. Defaults to 16 MiB if zero.
	// Server-generated objects (thumbnails, exports) fit easily within
	// this; anything larger is misuse and must use PresignPut instead.
	MaxPutBytes int64
}

const defaultMaxPutBytes = 16 << 20

// Client is a thin wrapper over the S3 SDK with presigner hooks attached.
type Client struct {
	s3          *s3.Client
	presigner   *s3.PresignClient
	log         *slog.Logger
	maxPutBytes int64
}

// New builds an S3 client. The provided ctx bounds only credential
// loading; the returned client is long-lived.
func New(ctx context.Context, cfg Config) (*Client, error) {
	if cfg.AccessKey == "" || cfg.SecretKey == "" {
		return nil, errors.New("storage: access/secret key required")
	}

	region := cfg.Region
	if region == "" {
		region = "us-east-1"
	}

	log := cfg.Logger
	if log == nil {
		log = slog.Default()
	}

	awsCfg, err := awsconfig.LoadDefaultConfig(ctx,
		awsconfig.WithRegion(region),
		awsconfig.WithCredentialsProvider(
			credentials.NewStaticCredentialsProvider(cfg.AccessKey, cfg.SecretKey, ""),
		),
	)
	if err != nil {
		return nil, fmt.Errorf("load aws config: %w", err)
	}

	pathStyle := cfg.UsePathStyle || cfg.Endpoint != ""

	s3client := s3.NewFromConfig(awsCfg, func(o *s3.Options) {
		if cfg.Endpoint != "" {
			o.BaseEndpoint = aws.String(cfg.Endpoint)
		}
		o.UsePathStyle = pathStyle
	})

	log.Info("s3 client ready",
		"endpoint", cfg.Endpoint,
		"region", region,
		"path_style", pathStyle,
	)

	maxPut := cfg.MaxPutBytes
	if maxPut <= 0 {
		maxPut = defaultMaxPutBytes
	}

	return &Client{
		s3:          s3client,
		presigner:   s3.NewPresignClient(s3client),
		log:         log,
		maxPutBytes: maxPut,
	}, nil
}

// Ping verifies the endpoint and credentials by issuing a HeadBucket
// against the supplied bucket. Wire this into pkg/health.Register so
// readiness flips to degraded when object storage is unreachable.
//
// HeadBucket returns success when the bucket exists and credentials
// can read it; missing bucket / wrong creds / wrong endpoint all fail.
func (c *Client) Ping(ctx context.Context, bucket string) error {
	if bucket == "" {
		return errors.New("storage: bucket is required for Ping")
	}
	_, err := c.s3.HeadBucket(ctx, &s3.HeadBucketInput{
		Bucket: aws.String(bucket),
	})
	if err != nil {
		return fmt.Errorf("ping bucket %s: %w", bucket, err)
	}
	return nil
}

// Put uploads body to bucket/key. Use only for small server-generated
// objects (thumbnails, exports). Client uploads must use PresignPut.
// contentType is required so downstream consumers (and the provider's
// own Content-Type metadata) aren't left guessing.
func (c *Client) Put(ctx context.Context, bucket, key string, body io.Reader, contentType string) error {
	if err := validateRef(bucket, key); err != nil {
		return err
	}
	if contentType == "" {
		return errors.New("storage: contentType is required")
	}
	// Cap the body. LimitReader stops at maxPutBytes+1; the counter lets
	// us detect overflow after the upload completes and remove the
	// truncated object so callers don't see a partial result.
	limited := &countingReader{r: io.LimitReader(body, c.maxPutBytes+1)}
	_, err := c.s3.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(bucket),
		Key:         aws.String(key),
		Body:        limited,
		ContentType: aws.String(contentType),
	})
	if err != nil {
		return fmt.Errorf("put %s/%s: %w", bucket, key, err)
	}
	if limited.n > c.maxPutBytes {
		// Best-effort cleanup; the object landed truncated.
		_ = c.Delete(context.Background(), bucket, key)
		return fmt.Errorf("storage: put %s/%s exceeded %d bytes", bucket, key, c.maxPutBytes)
	}
	return nil
}

type countingReader struct {
	r io.Reader
	n int64
}

func (c *countingReader) Read(p []byte) (int, error) {
	n, err := c.r.Read(p)
	c.n += int64(n)
	return n, err
}

// Get returns the object body. The caller MUST close the returned reader.
// Returns ErrNotFound if the object does not exist.
func (c *Client) Get(ctx context.Context, bucket, key string) (io.ReadCloser, string, error) {
	if err := validateRef(bucket, key); err != nil {
		return nil, "", err
	}
	out, err := c.s3.GetObject(ctx, &s3.GetObjectInput{
		Bucket: aws.String(bucket),
		Key:    aws.String(key),
	})
	if err != nil {
		if isNotFound(err) {
			return nil, "", ErrNotFound
		}
		return nil, "", fmt.Errorf("get %s/%s: %w", bucket, key, err)
	}
	ct := ""
	if out.ContentType != nil {
		ct = *out.ContentType
	}
	return out.Body, ct, nil
}

// ObjectInfo is the result of Head — used to verify a presigned upload landed.
type ObjectInfo struct {
	Size        int64
	ContentType string
	ETag        string
}

// Head fetches object metadata without the body. Returns ErrNotFound if
// the object does not exist — useful for verifying a presigned upload landed.
func (c *Client) Head(ctx context.Context, bucket, key string) (ObjectInfo, error) {
	if err := validateRef(bucket, key); err != nil {
		return ObjectInfo{}, err
	}
	out, err := c.s3.HeadObject(ctx, &s3.HeadObjectInput{
		Bucket: aws.String(bucket),
		Key:    aws.String(key),
	})
	if err != nil {
		if isNotFound(err) {
			return ObjectInfo{}, ErrNotFound
		}
		return ObjectInfo{}, fmt.Errorf("head %s/%s: %w", bucket, key, err)
	}
	info := ObjectInfo{}
	if out.ContentLength != nil {
		info.Size = *out.ContentLength
	}
	if out.ContentType != nil {
		info.ContentType = *out.ContentType
	}
	if out.ETag != nil {
		info.ETag = *out.ETag
	}
	return info, nil
}

// Delete removes an object. S3 returns success even if the object did
// not exist, so this is idempotent.
func (c *Client) Delete(ctx context.Context, bucket, key string) error {
	if err := validateRef(bucket, key); err != nil {
		return err
	}
	_, err := c.s3.DeleteObject(ctx, &s3.DeleteObjectInput{
		Bucket: aws.String(bucket),
		Key:    aws.String(key),
	})
	if err != nil {
		return fmt.Errorf("delete %s/%s: %w", bucket, key, err)
	}
	return nil
}

// PresignedRequest is a presigned HTTP request. The Flutter app must
// use the exact Method + URL and include every header in SignedHeaders;
// missing or extra signed headers make the signature invalid. Some
// providers (Backblaze B2) require headers the SDK adds automatically
// like `x-amz-content-sha256` — that's why we expose them.
type PresignedRequest struct {
	Method        string
	URL           string
	SignedHeaders http.Header
}

// PresignPut returns a presigned PUT for direct client upload. The
// content-type the client sends MUST match contentType. ttl must be
// in [1m, 1h]; values outside this range return an error so callers
// don't silently get a different lifetime than they asked for.
func (c *Client) PresignPut(ctx context.Context, bucket, key string, ttl time.Duration, contentType string) (PresignedRequest, error) {
	if err := validateRef(bucket, key); err != nil {
		return PresignedRequest{}, err
	}
	if err := validateTTL(ttl); err != nil {
		return PresignedRequest{}, err
	}
	if contentType == "" {
		// The signed Content-Type becomes part of the canonical request.
		// Empty is technically valid but most HTTP clients refuse to send
		// a literal empty Content-Type, so the upload would 403 at the
		// provider with no useful diagnostics.
		return PresignedRequest{}, errors.New("storage: contentType is required for presigned put")
	}
	req, err := c.presigner.PresignPutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(bucket),
		Key:         aws.String(key),
		ContentType: aws.String(contentType),
	}, s3.WithPresignExpires(ttl))
	if err != nil {
		return PresignedRequest{}, fmt.Errorf("presign put %s/%s: %w", bucket, key, err)
	}
	return PresignedRequest{
		Method:        req.Method,
		URL:           req.URL,
		SignedHeaders: req.SignedHeader,
	}, nil
}

// PresignGet returns a time-limited download URL. ttl must be in [1m, 1h].
func (c *Client) PresignGet(ctx context.Context, bucket, key string, ttl time.Duration) (PresignedRequest, error) {
	if err := validateRef(bucket, key); err != nil {
		return PresignedRequest{}, err
	}
	if err := validateTTL(ttl); err != nil {
		return PresignedRequest{}, err
	}
	req, err := c.presigner.PresignGetObject(ctx, &s3.GetObjectInput{
		Bucket: aws.String(bucket),
		Key:    aws.String(key),
	}, s3.WithPresignExpires(ttl))
	if err != nil {
		return PresignedRequest{}, fmt.Errorf("presign get %s/%s: %w", bucket, key, err)
	}
	return PresignedRequest{
		Method:        req.Method,
		URL:           req.URL,
		SignedHeaders: req.SignedHeader,
	}, nil
}

const (
	minPresignTTL = time.Minute
	maxPresignTTL = time.Hour
)

func validateTTL(ttl time.Duration) error {
	if ttl < minPresignTTL || ttl > maxPresignTTL {
		return fmt.Errorf("storage: ttl must be in [%s, %s], got %s", minPresignTTL, maxPresignTTL, ttl)
	}
	return nil
}

func validateRef(bucket, key string) error {
	if bucket == "" {
		return errors.New("storage: bucket is required")
	}
	if key == "" {
		return errors.New("storage: key is required")
	}
	return nil
}

func isNotFound(err error) bool {
	if _, ok := errors.AsType[*types.NoSuchKey](err); ok {
		return true
	}
	if _, ok := errors.AsType[*types.NotFound](err); ok {
		return true
	}
	// HeadObject returns a generic APIError with code "NotFound" — no
	// typed error from the SDK in this case.
	var apiErr smithy.APIError
	if errors.As(err, &apiErr) && apiErr.ErrorCode() == "NotFound" {
		return true
	}
	return false
}
