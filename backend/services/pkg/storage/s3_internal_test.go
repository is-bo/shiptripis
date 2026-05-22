package storage

import (
	"bytes"
	"errors"
	"io"
	"strings"
	"testing"
)

func TestLimitErrReader_ExactFit(t *testing.T) {
	body := strings.Repeat("a", 10)
	lr := &limitErrReader{r: strings.NewReader(body), max: 10}

	got, err := io.ReadAll(lr)
	if err != nil {
		t.Fatalf("ReadAll: %v", err)
	}
	if string(got) != body {
		t.Fatalf("body = %q, want %q", got, body)
	}
}

func TestLimitErrReader_OneByteOver(t *testing.T) {
	body := strings.Repeat("a", 11)
	lr := &limitErrReader{r: strings.NewReader(body), max: 10}

	_, err := io.ReadAll(lr)
	if !errors.Is(err, ErrTooLarge) {
		t.Fatalf("err = %v, want ErrTooLarge", err)
	}
}

func TestLimitErrReader_NeverReturnsBytesWithErrTooLarge(t *testing.T) {
	// io.Reader contract: when n>0, callers may legitimately ignore err.
	// Verify we never surface (n>0, ErrTooLarge) in a single Read call.
	body := bytes.Repeat([]byte("a"), 1024)
	lr := &limitErrReader{r: bytes.NewReader(body), max: 100}

	buf := make([]byte, 256)
	for {
		n, err := lr.Read(buf)
		if n > 0 && err != nil && !errors.Is(err, io.EOF) {
			t.Fatalf("contract violation: n=%d, err=%v", n, err)
		}
		if err != nil {
			if !errors.Is(err, ErrTooLarge) {
				t.Fatalf("final err = %v, want ErrTooLarge", err)
			}
			return
		}
	}
}
