// Package contracttest — общие тесты поведения портов. Их обязана проходить
// любая реализация: фейк в памяти и postgres-реализация разработчика БД.
//
// Использование в пакете реализации:
//
//	func TestContract(t *testing.T) {
//		contracttest.Run(t, func(t *testing.T) contracttest.Env { ... })
//	}
package contracttest

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/aliss3046/cookingApp/api/internal/domain"
	"github.com/aliss3046/cookingApp/api/internal/ports"
)

type Repos interface {
	ports.RecipeRepo
	ports.VoteRepo
	ports.PlanRepo
	ports.PantryRepo
	ports.CartRepo
	ports.PriceRepo
	ports.JobRepo
}

// Env — чистое окружение на один тест: две пары по два участника
// и одно общее блюдо.
type Env struct {
	Repos          Repos
	CoupleA        domain.ID
	UserA1, UserA2 domain.ID
	CoupleB        domain.ID
	UserB1         domain.ID
	SharedRecipeID domain.ID
}

func Run(t *testing.T, newEnv func(t *testing.T) Env) {
	tests := map[string]func(*testing.T, Env){
		"RecipesIsolatedBetweenCouples": recipesIsolated,
		"SharedRecipeCannotBeDeleted":   sharedRecipeNotDeletable,
		"VotesUpsertAndVisibleToCouple": votesUpsert,
		"PlansIsolatedBetweenCouples":   plansIsolated,
		"PantryReplace":                 pantryReplace,
		"CartLinesLifecycle":            cartLines,
		"JobsIsolatedBetweenCouples":    jobsIsolated,
	}
	for name, fn := range tests {
		t.Run(name, func(t *testing.T) { fn(t, newEnv(t)) })
	}
}

var ctx = context.Background()

// must(f())(t) — проверяет ошибку и возвращает значение.
func must[T any](v T, err error) func(*testing.T) T {
	return func(t *testing.T) T {
		t.Helper()
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		return v
	}
}

func wantNotFound(t *testing.T, err error) {
	t.Helper()
	if !errors.Is(err, ports.ErrNotFound) {
		t.Fatalf("want ErrNotFound, got %v", err)
	}
}

func newRecipe(title string) domain.Recipe {
	return domain.Recipe{
		Title: title, DefaultServings: 2, Status: domain.RecipeActive,
		Ingredients: []domain.RecipeIngredient{{QtyPerServing: 100, Unit: domain.UnitGram, RawText: "100 г"}},
	}
}

func recipesIsolated(t *testing.T, e Env) {
	r := must(e.Repos.CreateRecipe(ctx, e.CoupleA, newRecipe("Борщ")))(t)

	listA := must(e.Repos.ListRecipes(ctx, e.CoupleA, ports.RecipeFilter{}))(t)
	if !containsRecipe(listA, r.ID) || !containsRecipe(listA, e.SharedRecipeID) {
		t.Fatalf("couple A must see own and shared recipes")
	}
	listB := must(e.Repos.ListRecipes(ctx, e.CoupleB, ports.RecipeFilter{}))(t)
	if containsRecipe(listB, r.ID) {
		t.Fatalf("couple B must not see couple A recipe")
	}
	if !containsRecipe(listB, e.SharedRecipeID) {
		t.Fatalf("couple B must see shared recipe")
	}
	_, err := e.Repos.GetRecipes(ctx, e.CoupleB, []domain.ID{r.ID})
	wantNotFound(t, err)
	_, err = e.Repos.UpdateRecipe(ctx, e.CoupleB, r)
	wantNotFound(t, err)
	wantNotFound(t, e.Repos.DeleteRecipe(ctx, e.CoupleB, r.ID))

	if err := e.Repos.DeleteRecipe(ctx, e.CoupleA, r.ID); err != nil {
		t.Fatal(err)
	}
	_, err = e.Repos.GetRecipes(ctx, e.CoupleA, []domain.ID{r.ID})
	wantNotFound(t, err)
}

func sharedRecipeNotDeletable(t *testing.T, e Env) {
	wantNotFound(t, e.Repos.DeleteRecipe(ctx, e.CoupleA, e.SharedRecipeID))
	got := must(e.Repos.GetRecipes(ctx, e.CoupleA, []domain.ID{e.SharedRecipeID}))(t)
	if len(got) != 1 {
		t.Fatalf("shared recipe must still exist")
	}
}

func votesUpsert(t *testing.T, e Env) {
	put := func(user domain.ID, v domain.VoteValue) {
		t.Helper()
		if err := e.Repos.PutVote(ctx, e.CoupleA, domain.Vote{RecipeID: e.SharedRecipeID, UserID: user, Value: v}); err != nil {
			t.Fatal(err)
		}
	}
	put(e.UserA1, domain.VoteWant)
	put(e.UserA1, domain.VoteDontWant) // повторный голос заменяет первый
	put(e.UserA2, domain.VoteNeutral)

	votes := must(e.Repos.ListVotes(ctx, e.CoupleA))(t)
	if len(votes) != 2 {
		t.Fatalf("want 2 votes, got %d", len(votes))
	}
	for _, v := range votes {
		if v.UserID == e.UserA1 && v.Value != domain.VoteDontWant {
			t.Fatalf("vote must be replaced, got %s", v.Value)
		}
	}
	if got := must(e.Repos.ListVotes(ctx, e.CoupleB))(t); len(got) != 0 {
		t.Fatalf("couple B must not see couple A votes")
	}
	// Нельзя голосовать за чужого участника.
	err := e.Repos.PutVote(ctx, e.CoupleA, domain.Vote{RecipeID: e.SharedRecipeID, UserID: e.UserB1, Value: domain.VoteWant})
	wantNotFound(t, err)
}

func newPlan(t *testing.T, e Env, couple domain.ID) domain.Plan {
	t.Helper()
	return must(e.Repos.CreatePlan(ctx, domain.Plan{
		CoupleID: couple, WeekStart: time.Date(2026, 10, 12, 0, 0, 0, 0, time.UTC), Status: "draft",
	}))(t)
}

func plansIsolated(t *testing.T, e Env) {
	p := newPlan(t, e, e.CoupleA)
	it := must(e.Repos.AddPlanItem(ctx, e.CoupleA, domain.PlanItem{PlanID: p.ID, RecipeID: e.SharedRecipeID, Servings: 2}))(t)

	it.Servings = 4
	date := time.Date(2026, 10, 14, 0, 0, 0, 0, time.UTC)
	it.Date, it.Meal = &date, domain.MealDinner
	upd := must(e.Repos.UpdatePlanItem(ctx, e.CoupleA, it))(t)
	if upd.Servings != 4 || upd.Meal != domain.MealDinner || upd.Date == nil || !upd.Date.Equal(date) {
		t.Fatalf("servings/date/meal not updated: %+v", upd)
	}
	items := must(e.Repos.ListPlanItems(ctx, e.CoupleA, p.ID))(t)
	if len(items) != 1 || items[0].Servings != 4 {
		t.Fatalf("unexpected plan items: %+v", items)
	}

	_, err := e.Repos.GetPlan(ctx, e.CoupleB, p.ID)
	wantNotFound(t, err)
	_, err = e.Repos.ListPlanItems(ctx, e.CoupleB, p.ID)
	wantNotFound(t, err)
	_, err = e.Repos.AddPlanItem(ctx, e.CoupleB, domain.PlanItem{PlanID: p.ID, RecipeID: e.SharedRecipeID, Servings: 1})
	wantNotFound(t, err)
	_, err = e.Repos.UpdatePlanItem(ctx, e.CoupleB, it)
	wantNotFound(t, err)
	if plans := must(e.Repos.ListPlans(ctx, e.CoupleB))(t); len(plans) != 0 {
		t.Fatalf("couple B must not see couple A plans")
	}
}

func pantryReplace(t *testing.T, e Env) {
	ing := domain.ID("ingredient-1")
	first := []domain.PantryItem{{IngredientID: ing, Qty: 200, Unit: domain.UnitGram, Source: domain.PantryManual}}
	if err := e.Repos.ReplacePantry(ctx, e.CoupleA, first); err != nil {
		t.Fatal(err)
	}
	if err := e.Repos.ReplacePantry(ctx, e.CoupleA, nil); err != nil {
		t.Fatal(err)
	}
	if got := must(e.Repos.GetPantry(ctx, e.CoupleA))(t); len(got) != 0 {
		t.Fatalf("replace must clear previous items, got %+v", got)
	}
	if err := e.Repos.ReplacePantry(ctx, e.CoupleA, first); err != nil {
		t.Fatal(err)
	}
	if got := must(e.Repos.GetPantry(ctx, e.CoupleB))(t); len(got) != 0 {
		t.Fatalf("couple B must not see couple A pantry")
	}
}

func cartLines(t *testing.T, e Env) {
	p := newPlan(t, e, e.CoupleA)
	l := must(e.Repos.AddCartLine(ctx, e.CoupleA, domain.CartLine{
		PlanID: p.ID, Title: "Салфетки", Qty: 1, Unit: domain.UnitPiece, AddedManually: true,
	}))(t)
	ing, product := domain.ID("ingredient-1"), domain.ID("product-1")
	l.Excluded, l.QtyOverridden, l.Qty = true, true, 3
	l.IngredientID, l.ChosenProductID = &ing, &product
	got := must(e.Repos.UpdateCartLine(ctx, e.CoupleA, l))(t)
	if !got.Excluded || !got.QtyOverridden || got.Qty != 3 {
		t.Fatalf("excluded/qty override not saved: %+v", got)
	}
	if got.IngredientID == nil || *got.IngredientID != ing || got.ChosenProductID == nil || *got.ChosenProductID != product {
		t.Fatalf("ingredient/chosen product not saved: %+v", got)
	}

	_, err := e.Repos.ListCartLines(ctx, e.CoupleB, p.ID)
	wantNotFound(t, err)
	_, err = e.Repos.UpdateCartLine(ctx, e.CoupleB, l)
	wantNotFound(t, err)
	wantNotFound(t, e.Repos.DeleteCartLine(ctx, e.CoupleB, l.ID))

	if err := e.Repos.DeleteCartLine(ctx, e.CoupleA, l.ID); err != nil {
		t.Fatal(err)
	}
	if lines := must(e.Repos.ListCartLines(ctx, e.CoupleA, p.ID))(t); len(lines) != 0 {
		t.Fatalf("line must be deleted")
	}
}

func jobsIsolated(t *testing.T, e Env) {
	j := must(e.Repos.EnqueueJob(ctx, domain.Job{CoupleID: e.CoupleA, Kind: domain.JobQuote}))(t)
	if j.Status != domain.JobQueued {
		t.Fatalf("new job must be queued, got %s", j.Status)
	}
	if got := must(e.Repos.GetJob(ctx, e.CoupleA, j.ID))(t); got.Kind != domain.JobQuote {
		t.Fatalf("unexpected job: %+v", got)
	}
	_, err := e.Repos.GetJob(ctx, e.CoupleB, j.ID)
	wantNotFound(t, err)
}

func containsRecipe(rs []domain.Recipe, id domain.ID) bool {
	for _, r := range rs {
		if r.ID == id {
			return true
		}
	}
	return false
}
