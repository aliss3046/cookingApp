package domain_test

import (
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/aliss3046/cookingApp/api/internal/domain"
)

func day(y int, m time.Month, d int) *time.Time {
	t := time.Date(y, m, d, 15, 30, 0, 0, time.FixedZone("MSK", 3*3600))
	return &t
}

func TestPlanItemValidate(t *testing.T) {
	// неделя с понедельника 12 октября 2026 по воскресенье 18-го
	week := time.Date(2026, 10, 12, 0, 0, 0, 0, time.UTC)

	tests := []struct {
		name    string
		item    domain.PlanItem
		wantErr string // подстрока ошибки, пусто — валидно
	}{
		{"без даты и приёма пищи", domain.PlanItem{Servings: 2}, ""},
		{"дата и приём пищи", domain.PlanItem{Servings: 2, Date: day(2026, 10, 14), Meal: domain.MealDinner}, ""},
		{"дата без приёма пищи", domain.PlanItem{Servings: 1, Date: day(2026, 10, 14)}, ""},
		{"первый день недели", domain.PlanItem{Servings: 1, Date: day(2026, 10, 12)}, ""},
		{"последний день недели", domain.PlanItem{Servings: 1, Date: day(2026, 10, 18)}, ""},
		{"день до недели", domain.PlanItem{Servings: 1, Date: day(2026, 10, 11)}, "outside the plan week"},
		{"день после недели", domain.PlanItem{Servings: 1, Date: day(2026, 10, 19)}, "outside the plan week"},
		{"порций нет", domain.PlanItem{Servings: 0}, "servings"},
		{"приём пищи без даты", domain.PlanItem{Servings: 1, Meal: domain.MealLunch}, "requires a date"},
		{"неизвестный приём пищи", domain.PlanItem{Servings: 1, Date: day(2026, 10, 14), Meal: "brunch"}, "unknown meal"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			err := tc.item.Validate(week)
			if tc.wantErr == "" {
				if err != nil {
					t.Fatalf("unexpected error: %v", err)
				}
				return
			}
			if !errors.Is(err, domain.ErrInvalidPlanItem) || !strings.Contains(err.Error(), tc.wantErr) {
				t.Fatalf("want ErrInvalidPlanItem containing %q, got %v", tc.wantErr, err)
			}
		})
	}
}

func TestMealValid(t *testing.T) {
	for _, m := range []domain.Meal{domain.MealBreakfast, domain.MealLunch, domain.MealDinner, domain.MealSnack} {
		if !m.Valid() {
			t.Errorf("%s must be valid", m)
		}
	}
	if domain.Meal("").Valid() || domain.Meal("brunch").Valid() {
		t.Error("empty and unknown meals must be invalid")
	}
}
