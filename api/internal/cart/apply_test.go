package cart_test

import (
	"reflect"
	"testing"

	"github.com/aliss3046/cookingApp/api/internal/cart"
	"github.com/aliss3046/cookingApp/api/internal/domain"
)

func idp(s string) *domain.ID { id := domain.ID(s); return &id }

func TestApplyLines(t *testing.T) {
	lines := []domain.CartLine{
		{ID: "l1", IngredientID: idp("flour"), Excluded: true},
		{ID: "l2", IngredientID: idp("milk"), Qty: 300, Unit: domain.UnitGram, QtyOverridden: true, ChosenProductID: idp("pm")},
		{ID: "l3", IngredientID: idp("tomato"), Title: "Помидоры", Qty: 500, Unit: domain.UnitGram, AddedManually: true, ChosenProductID: idp("pt")},
		{ID: "l4", Title: "Салфетки", Qty: 2, Unit: domain.UnitPiece, AddedManually: true},
		{ID: "l5", Title: "Убрано", Qty: 1, Unit: domain.UnitPiece, AddedManually: true, Excluded: true},
		// своё количество ручной позиции — это её Qty, а не переопределение
		{ID: "l6", IngredientID: idp("egg"), Qty: 6, Unit: domain.UnitPiece, AddedManually: true, QtyOverridden: true},
		// обычная строка без пометок ничего не меняет
		{ID: "l7", IngredientID: idp("salt"), Qty: 5, Unit: domain.UnitGram},
		{ID: "l8", Title: "без ингредиента", Qty: 1},
	}

	var in cart.Input
	in.ApplyLines(lines)
	in.ApplyLines(nil) // повторный вызов с уже созданными картами не ломает вход

	if !reflect.DeepEqual(in.Excluded, map[domain.ID]bool{"flour": true}) {
		t.Errorf("excluded: %v", in.Excluded)
	}
	wantOverrides := map[domain.ID]cart.QtyOverride{"milk": {Qty: 300, Unit: domain.UnitGram}}
	if !reflect.DeepEqual(in.QtyOverrides, wantOverrides) {
		t.Errorf("overrides: %v", in.QtyOverrides)
	}
	wantChosen := map[domain.ID]domain.ID{"milk": "pm", "tomato": "pt"}
	if !reflect.DeepEqual(in.ChosenProducts, wantChosen) {
		t.Errorf("chosen: %v", in.ChosenProducts)
	}
	var manual []domain.ID
	for _, m := range in.Manual {
		manual = append(manual, m.ID)
	}
	if !reflect.DeepEqual(manual, []domain.ID{"l3", "l4", "l6"}) {
		t.Errorf("manual: %v", manual)
	}

	// map-ы не создаются, пока в них нечего класть
	var empty cart.Input
	empty.ApplyLines([]domain.CartLine{{ID: "x", Title: "Салфетки", AddedManually: true}})
	if empty.Excluded != nil || empty.QtyOverrides != nil || empty.ChosenProducts != nil {
		t.Errorf("maps must stay nil: %+v", empty)
	}
}

func TestManualLinkedTitleFallback(t *testing.T) {
	// в справочнике нет названия ингредиента: берём название ручной позиции
	c, err := cart.Build(cart.Input{
		Manual: []domain.CartLine{{
			IngredientID: idp("carrot"), Title: "Морковь", Qty: 300, Unit: domain.UnitGram, AddedManually: true,
		}},
		Now: now,
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(c.Lines) != 1 || c.Lines[0].Title != "Морковь" || c.Lines[0].Manual {
		t.Fatalf("unexpected lines: %+v", c.Lines)
	}
}

func TestErrUnknownRecipeMessage(t *testing.T) {
	_, err := cart.Build(cart.Input{Plan: []domain.PlanItem{{RecipeID: "ghost"}}, Now: now})
	if err == nil || err.Error() != `cart: unknown recipe "ghost"` {
		t.Fatalf("unexpected error: %v", err)
	}
}
