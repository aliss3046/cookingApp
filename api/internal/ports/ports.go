// Package ports описывает, какие данные нужны логике API. Это договор между
// командой логики и разработчиком БД: интерфейсы меняются только через PR,
// который видят обе стороны.
//
// Реализации:
//   - ports/memory — фейки в памяти для тестов логики;
//   - postgres-реализация — пишет разработчик БД.
//
// Каждая реализация обязана проходить ports/contracttest.
//
// coupleID всегда передаётся явно (из токена). Чужие данные пары возвращаются
// как ErrNotFound, а не ErrForbidden, чтобы не раскрывать их существование.
package ports

import (
	"context"
	"errors"

	"github.com/aliss3046/cookingApp/api/internal/domain"
)

var (
	ErrNotFound = errors.New("not found")
	ErrConflict = errors.New("conflict")
)

type RecipeFilter struct {
	Query  string
	Tag    string
	Status domain.RecipeStatus // пусто — любой
}

type RecipeRepo interface {
	// ListRecipes возвращает общие блюда и блюда пары.
	ListRecipes(ctx context.Context, coupleID domain.ID, f RecipeFilter) ([]domain.Recipe, error)
	GetRecipes(ctx context.Context, coupleID domain.ID, ids []domain.ID) ([]domain.Recipe, error)
	CreateRecipe(ctx context.Context, coupleID domain.ID, r domain.Recipe) (domain.Recipe, error)
	UpdateRecipe(ctx context.Context, coupleID domain.ID, r domain.Recipe) (domain.Recipe, error)
	// DeleteRecipe удаляет только блюдо пары; общее блюдо — ErrNotFound.
	DeleteRecipe(ctx context.Context, coupleID domain.ID, id domain.ID) error
}

type VoteRepo interface {
	PutVote(ctx context.Context, coupleID domain.ID, v domain.Vote) error
	// ListVotes возвращает голоса обоих участников пары.
	ListVotes(ctx context.Context, coupleID domain.ID) ([]domain.Vote, error)
}

type PlanRepo interface {
	ListPlans(ctx context.Context, coupleID domain.ID) ([]domain.Plan, error)
	GetPlan(ctx context.Context, coupleID, planID domain.ID) (domain.Plan, error)
	CreatePlan(ctx context.Context, p domain.Plan) (domain.Plan, error)
	ListPlanItems(ctx context.Context, coupleID, planID domain.ID) ([]domain.PlanItem, error)
	AddPlanItem(ctx context.Context, coupleID domain.ID, it domain.PlanItem) (domain.PlanItem, error)
	UpdatePlanItem(ctx context.Context, coupleID domain.ID, it domain.PlanItem) (domain.PlanItem, error)
}

type PantryRepo interface {
	GetPantry(ctx context.Context, coupleID domain.ID) ([]domain.PantryItem, error)
	// ReplacePantry целиком заменяет список запасов пары.
	ReplacePantry(ctx context.Context, coupleID domain.ID, items []domain.PantryItem) error
}

type CartRepo interface {
	ListCartLines(ctx context.Context, coupleID, planID domain.ID) ([]domain.CartLine, error)
	AddCartLine(ctx context.Context, coupleID domain.ID, l domain.CartLine) (domain.CartLine, error)
	UpdateCartLine(ctx context.Context, coupleID domain.ID, l domain.CartLine) (domain.CartLine, error)
	DeleteCartLine(ctx context.Context, coupleID, lineID domain.ID) error
}

// PriceRepo только читает: цены пишет Python-воркер.
type PriceRepo interface {
	// MappedProducts возвращает товары, сопоставленные ингредиентам, в магазинах пары.
	MappedProducts(ctx context.Context, ingredientIDs []domain.ID) (map[domain.ID][]domain.Product, error)
	// LatestPrices возвращает последнюю цену каждого товара по адресу.
	LatestPrices(ctx context.Context, locationID domain.ID, productIDs []domain.ID) (map[domain.ID]domain.Price, error)
}

// JobRepo: API ставит задачи и читает статус, выполняет их Python-воркер.
type JobRepo interface {
	EnqueueJob(ctx context.Context, j domain.Job) (domain.Job, error)
	GetJob(ctx context.Context, coupleID, jobID domain.ID) (domain.Job, error)
}
