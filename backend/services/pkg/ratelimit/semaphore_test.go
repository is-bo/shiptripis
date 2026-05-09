package ratelimit

import (
	"context"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestSemaphore_TryAcquireUpToCapacity(t *testing.T) {
	s := NewSemaphore(3)
	for i := 0; i < 3; i++ {
		if !s.TryAcquire() {
			t.Fatalf("TryAcquire %d: want true, got false", i)
		}
	}
	if s.TryAcquire() {
		t.Fatalf("TryAcquire over capacity: want false, got true")
	}
}

func TestSemaphore_ReleaseFreesSlot(t *testing.T) {
	s := NewSemaphore(1)
	if !s.TryAcquire() {
		t.Fatal("first TryAcquire should succeed")
	}
	if s.TryAcquire() {
		t.Fatal("second TryAcquire should fail when full")
	}
	s.Release()
	if !s.TryAcquire() {
		t.Fatal("TryAcquire after Release should succeed")
	}
}

func TestSemaphore_AcquireBlocksUntilRelease(t *testing.T) {
	s := NewSemaphore(1)
	if !s.TryAcquire() {
		t.Fatal("setup TryAcquire failed")
	}

	acquired := make(chan struct{})
	go func() {
		_ = s.Acquire(context.Background())
		close(acquired)
	}()

	select {
	case <-acquired:
		t.Fatal("Acquire returned before Release")
	case <-time.After(20 * time.Millisecond):
	}

	s.Release()
	select {
	case <-acquired:
	case <-time.After(100 * time.Millisecond):
		t.Fatal("Acquire did not return after Release")
	}
}

func TestSemaphore_AcquireRespectsContextCancel(t *testing.T) {
	s := NewSemaphore(1)
	if !s.TryAcquire() {
		t.Fatal("setup TryAcquire failed")
	}

	ctx, cancel := context.WithCancel(context.Background())
	errCh := make(chan error, 1)
	go func() {
		errCh <- s.Acquire(ctx)
	}()

	cancel()
	select {
	case err := <-errCh:
		if err == nil {
			t.Fatal("Acquire after cancel: want error, got nil")
		}
		if err != context.Canceled {
			t.Fatalf("Acquire after cancel: want context.Canceled, got %v", err)
		}
	case <-time.After(100 * time.Millisecond):
		t.Fatal("Acquire did not return on context cancel")
	}
}

func TestSemaphore_AcquireRespectsContextDeadline(t *testing.T) {
	s := NewSemaphore(1)
	if !s.TryAcquire() {
		t.Fatal("setup TryAcquire failed")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
	defer cancel()
	err := s.Acquire(ctx)
	if err != context.DeadlineExceeded {
		t.Fatalf("Acquire timeout: want DeadlineExceeded, got %v", err)
	}
}

func TestSemaphore_NeverExceedsCapacityUnderLoad(t *testing.T) {
	const n = 10
	const goroutines = 200

	s := NewSemaphore(n)
	var inFlight atomic.Int32
	var maxObserved atomic.Int32
	var wg sync.WaitGroup

	for i := 0; i < goroutines; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if err := s.Acquire(context.Background()); err != nil {
				t.Errorf("Acquire: %v", err)
				return
			}
			cur := inFlight.Add(1)
			for {
				m := maxObserved.Load()
				if cur <= m || maxObserved.CompareAndSwap(m, cur) {
					break
				}
			}
			time.Sleep(time.Microsecond)
			inFlight.Add(-1)
			s.Release()
		}()
	}
	wg.Wait()

	if got := maxObserved.Load(); got > n {
		t.Fatalf("max in-flight: want <= %d, got %d", n, got)
	}
}

func TestSemaphore_ReleaseWithoutAcquirePanics(t *testing.T) {
	s := NewSemaphore(1)
	defer func() {
		if r := recover(); r == nil {
			t.Fatal("Release without Acquire: want panic, got none")
		}
	}()
	s.Release()
}

func TestSemaphore_NewWithZeroCapacityPanics(t *testing.T) {
	defer func() {
		if r := recover(); r == nil {
			t.Fatal("NewSemaphore(0): want panic, got none")
		}
	}()
	NewSemaphore(0)
}
