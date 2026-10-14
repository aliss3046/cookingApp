package domain_test

import (
	"testing"
	"time"

	"github.com/aliss3046/cookingApp/api/internal/domain"
)

func TestUnitValid(t *testing.T) {
	for _, u := range []domain.Unit{domain.UnitGram, domain.UnitMl, domain.UnitPiece} {
		if !u.Valid() {
			t.Errorf("%s must be valid", u)
		}
	}
	for _, u := range []domain.Unit{"", "kg", "tbsp"} {
		if u.Valid() {
			t.Errorf("%q must be invalid", u)
		}
	}
}

func TestPriceStaleBoundary(t *testing.T) {
	now := time.Date(2026, 10, 13, 12, 0, 0, 0, time.UTC)
	tests := []struct {
		age  time.Duration
		want bool
	}{
		{time.Hour, false},
		{72 * time.Hour, false}, // ровно 3 суток ещё не устарела
		{72*time.Hour + time.Second, true},
	}
	for _, tc := range tests {
		p := domain.Price{FetchedAt: now.Add(-tc.age)}
		if got := p.Stale(now); got != tc.want {
			t.Errorf("age %v: stale=%v, want %v", tc.age, got, tc.want)
		}
	}
}
