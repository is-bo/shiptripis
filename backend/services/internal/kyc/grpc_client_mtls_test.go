package kyc

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// writePEMCertAndKey generates a self-signed cert+key (CA or leaf) and writes
// them to disk, returning the two paths. Using ECDSA keeps key-gen fast so the
// test stays sub-second. Dates are fixed-relative (no Date.now concerns here —
// this is a normal test binary, not a workflow script).
func writePEMCertAndKey(t *testing.T, dir, name string, isCA bool) (certPath, keyPath string) {
	t.Helper()

	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("gen key: %v", err)
	}

	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject:      pkix.Name{CommonName: name},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(24 * time.Hour),
		KeyUsage:     x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth, x509.ExtKeyUsageServerAuth},
		DNSNames:     []string{name},
	}
	if isCA {
		tmpl.IsCA = true
		tmpl.BasicConstraintsValid = true
	}

	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatalf("create cert: %v", err)
	}

	certPath = filepath.Join(dir, name+".crt")
	keyPath = filepath.Join(dir, name+".key")

	certPEM, err := os.Create(certPath)
	if err != nil {
		t.Fatalf("create cert file: %v", err)
	}
	defer certPEM.Close()
	if err := pem.Encode(certPEM, &pem.Block{Type: "CERTIFICATE", Bytes: der}); err != nil {
		t.Fatalf("encode cert: %v", err)
	}

	keyDER, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		t.Fatalf("marshal key: %v", err)
	}
	keyPEM, err := os.Create(keyPath)
	if err != nil {
		t.Fatalf("create key file: %v", err)
	}
	defer keyPEM.Close()
	if err := pem.Encode(keyPEM, &pem.Block{Type: "PRIVATE KEY", Bytes: keyDER}); err != nil {
		t.Fatalf("encode key: %v", err)
	}
	return certPath, keyPath
}

func TestTLSCredentials_Valid(t *testing.T) {
	dir := t.TempDir()
	caCert, _ := writePEMCertAndKey(t, dir, "ca", true)
	clientCert, clientKey := writePEMCertAndKey(t, dir, "client", false)

	creds, err := tlsCredentials(GRPCClientConfig{
		CACertPath:     caCert,
		ClientCertPath: clientCert,
		ClientKeyPath:  clientKey,
	})
	if err != nil {
		t.Fatalf("tlsCredentials with valid certs: %v", err)
	}
	if creds == nil {
		t.Fatal("tlsCredentials returned nil credentials")
	}
	// The credentials advertise TLS — proves we built real transport creds,
	// not the insecure fallback.
	if got := creds.Info().SecurityProtocol; got != "tls" {
		t.Errorf("SecurityProtocol = %q, want tls", got)
	}
}

func TestTLSCredentials_FailsLoud(t *testing.T) {
	dir := t.TempDir()
	caCert, _ := writePEMCertAndKey(t, dir, "ca", true)
	clientCert, clientKey := writePEMCertAndKey(t, dir, "client", false)

	// A file that exists but isn't a PEM certificate, to exercise the
	// AppendCertsFromPEM-returns-false branch distinctly from a missing file.
	garbage := filepath.Join(dir, "garbage.pem")
	if err := os.WriteFile(garbage, []byte("not a certificate"), 0o600); err != nil {
		t.Fatal(err)
	}

	tests := []struct {
		name string
		cfg  GRPCClientConfig
	}{
		{name: "empty paths", cfg: GRPCClientConfig{}},
		{name: "missing CA file", cfg: GRPCClientConfig{
			CACertPath: filepath.Join(dir, "nope.pem"), ClientCertPath: clientCert, ClientKeyPath: clientKey,
		}},
		{name: "CA not a cert", cfg: GRPCClientConfig{
			CACertPath: garbage, ClientCertPath: clientCert, ClientKeyPath: clientKey,
		}},
		{name: "missing client cert", cfg: GRPCClientConfig{
			CACertPath: caCert, ClientCertPath: filepath.Join(dir, "nope.crt"), ClientKeyPath: clientKey,
		}},
		{name: "mismatched key path", cfg: GRPCClientConfig{
			CACertPath: caCert, ClientCertPath: clientCert, ClientKeyPath: caCert, // wrong key for this cert
		}},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if _, err := tlsCredentials(tt.cfg); err == nil {
				t.Fatalf("expected error for %s, got nil", tt.name)
			}
		})
	}
}

// NewGRPCClient in mtls mode must fail loud at construction when certs are
// bad — before any dial. We can't assert a successful dial without a live
// mTLS server (that's the integration gap, same as the bearer happy path),
// but we CAN assert the credential-loading failure short-circuits boot.
func TestNewGRPCClient_MTLSBadCertsFailFast(t *testing.T) {
	_, err := NewGRPCClient(t.Context(), GRPCClientConfig{
		Target:         "django:50051",
		AuthMode:       GRPCAuthMTLS,
		CACertPath:     "/does/not/exist/ca.pem",
		ClientCertPath: "/does/not/exist/client.crt",
		ClientKeyPath:  "/does/not/exist/client.key",
		DialTimeout:    time.Second,
	}, nil)
	if err == nil {
		t.Fatal("expected mtls construction to fail on missing certs, got nil")
	}
}

func TestNewGRPCClient_BearerRequiresToken(t *testing.T) {
	_, err := NewGRPCClient(t.Context(), GRPCClientConfig{
		Target:   "django:50051",
		AuthMode: GRPCAuthBearer,
		// no BearerToken
		DialTimeout: time.Second,
	}, nil)
	if err == nil {
		t.Fatal("expected bearer mode without token to error, got nil")
	}
}

func TestNewGRPCClient_UnknownModeAndEmptyTarget(t *testing.T) {
	if _, err := NewGRPCClient(t.Context(), GRPCClientConfig{Target: "", AuthMode: GRPCAuthBearer}, nil); err == nil {
		t.Error("expected error for empty target")
	}
	if _, err := NewGRPCClient(t.Context(), GRPCClientConfig{Target: "x:1", AuthMode: "kerberos"}, nil); err == nil {
		t.Error("expected error for unknown auth mode")
	}
}
