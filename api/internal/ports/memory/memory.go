// Package memory — фейк всех портов в памяти. Используется в тестах логики
// и обязан вести себя так же, как postgres-реализация (см. ports/contracttest).
package memory

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/aliss3046/cookingApp/api/internal/domain"
	"github.com/aliss3046/cookingApp/api/internal/ports"
)

type Store struct {
	mu      sync.Mutex
	seq     int
	members map[domain.ID]domain.ID // user -> couple

	recipes   map[domain.ID]domain.Recipe
	votes     map[[2]domain.ID]domain.Vote // (recipe, user)
	plans     map[domain.ID]domain.Plan
	planItems map[domain.ID]domain.PlanItem
	pantry    map[domain.ID][]domain.PantryItem
	cartLines map[domain.ID]domain.CartLine
	products  map[domain.ID]domain.Product
	mapping   map[domain.ID][]domain.ID // ingredient -> products
	prices    []domain.Price
	jobs      map[domain.ID]domain.Job
}

var (
	_ ports.RecipeRepo = (*Store)(nil)
	_ ports.VoteRepo   = (*Store)(nil)
	_ ports.PlanRepo   = (*Store)(nil)
	_ ports.PantryRepo = (*Store)(nil)
	_ ports.CartRepo   = (*Store)(nil)
	_ ports.PriceRepo  = (*Store)(nil)
	_ ports.JobRepo    = (*Store)(nil)
)

func New() *Store {
	return &Store{
		members:   map[domain.ID]domain.ID{},
		recipes:   map[domain.ID]domain.Recipe{},
		votes:     map[[2]domain.ID]domain.Vote{},
		plans:     map[domain.ID]domain.Plan{},
		planItems: map[domain.ID]domain.PlanItem{},
		pantry:    map[domain.ID][]domain.PantryItem{},
		cartLines: map[domain.ID]domain.CartLine{},
		products:  map[domain.ID]domain.Product{},
		mapping:   map[domain.ID][]domain.ID{},
		jobs:      map[domain.ID]domain.Job{},
	}
}

func (s *Store) newID() domain.ID {
	s.seq++
	return domain.ID(fmt.Sprintf("mem-%d", s.seq))
}

// --- Сиды для тестов (в postgres это делают миграции/сиды) ---

func (s *Store) SeedMember(coupleID, userID domain.ID) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.members[userID] = coupleID
}

// SeedSharedRecipe добавляет общее блюдо (couple_id = null).
func (s *Store) SeedSharedRecipe(r domain.Recipe) domain.Recipe {
	s.mu.Lock()
	defer s.mu.Unlock()
	r.ID = s.newID()
	r.CoupleID = nil
	s.recipes[r.ID] = r
	return r
}

func (s *Store) SeedProduct(p domain.Product, ingredientIDs ...domain.ID) domain.Product {
	s.mu.Lock()
	defer s.mu.Unlock()
	p.ID = s.newID()
	s.products[p.ID] = p
	for _, ing := range ingredientIDs {
		s.mapping[ing] = append(s.mapping[ing], p.ID)
	}
	return p
}

func (s *Store) SeedPrice(p domain.Price) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.prices = append(s.prices, p)
}

// --- RecipeRepo ---

func (s *Store) visible(coupleID domain.ID, r domain.Recipe) bool {
	return r.CoupleID == nil || *r.CoupleID == coupleID
}

func (s *Store) ListRecipes(_ context.Context, coupleID domain.ID, f ports.RecipeFilter) ([]domain.Recipe, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var out []domain.Recipe
	for _, r := range s.recipes {
		if !s.visible(coupleID, r) {
			continue
		}
		if f.Status != "" && r.Status != f.Status {
			continue
		}
		if f.Tag != "" && !slices.Contains(r.Tags, f.Tag) {
			continue
		}
		if f.Query != "" && !strings.Contains(strings.ToLower(r.Title), strings.ToLower(f.Query)) {
			continue
		}
		out = append(out, r)
	}
	slices.SortFunc(out, func(a, b domain.Recipe) int { return strings.Compare(string(a.ID), string(b.ID)) })
	return out, nil
}

func (s *Store) GetRecipes(_ context.Context, coupleID domain.ID, ids []domain.ID) ([]domain.Recipe, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]domain.Recipe, 0, len(ids))
	for _, id := range ids {
		r, ok := s.recipes[id]
		if !ok || !s.visible(coupleID, r) {
			return nil, ports.ErrNotFound
		}
		out = append(out, r)
	}
	return out, nil
}

func (s *Store) CreateRecipe(_ context.Context, coupleID domain.ID, r domain.Recipe) (domain.Recipe, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	r.ID = s.newID()
	r.CoupleID = &coupleID
	s.recipes[r.ID] = r
	return r, nil
}

func (s *Store) UpdateRecipe(_ context.Context, coupleID domain.ID, r domain.Recipe) (domain.Recipe, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	old, ok := s.recipes[r.ID]
	if !ok || old.CoupleID == nil || *old.CoupleID != coupleID {
		return domain.Recipe{}, ports.ErrNotFound
	}
	r.CoupleID = old.CoupleID
	s.recipes[r.ID] = r
	return r, nil
}

func (s *Store) DeleteRecipe(_ context.Context, coupleID domain.ID, id domain.ID) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	r, ok := s.recipes[id]
	if !ok || r.CoupleID == nil || *r.CoupleID != coupleID {
		return ports.ErrNotFound
	}
	delete(s.recipes, id)
	return nil
}

// --- VoteRepo ---

func (s *Store) PutVote(_ context.Context, coupleID domain.ID, v domain.Vote) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.members[v.UserID] != coupleID {
		return ports.ErrNotFound
	}
	r, ok := s.recipes[v.RecipeID]
	if !ok || !s.visible(coupleID, r) {
		return ports.ErrNotFound
	}
	s.votes[[2]domain.ID{v.RecipeID, v.UserID}] = v
	return nil
}

func (s *Store) ListVotes(_ context.Context, coupleID domain.ID) ([]domain.Vote, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var out []domain.Vote
	for _, v := range s.votes {
		if s.members[v.UserID] == coupleID {
			out = append(out, v)
		}
	}
	return out, nil
}

// --- PlanRepo ---

func (s *Store) ListPlans(_ context.Context, coupleID domain.ID) ([]domain.Plan, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var out []domain.Plan
	for _, p := range s.plans {
		if p.CoupleID == coupleID {
			out = append(out, p)
		}
	}
	slices.SortFunc(out, func(a, b domain.Plan) int { return a.WeekStart.Compare(b.WeekStart) })
	return out, nil
}

func (s *Store) GetPlan(_ context.Context, coupleID, planID domain.ID) (domain.Plan, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.planOf(coupleID, planID)
}

func (s *Store) planOf(coupleID, planID domain.ID) (domain.Plan, error) {
	p, ok := s.plans[planID]
	if !ok || p.CoupleID != coupleID {
		return domain.Plan{}, ports.ErrNotFound
	}
	return p, nil
}

func (s *Store) CreatePlan(_ context.Context, p domain.Plan) (domain.Plan, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	p.ID = s.newID()
	s.plans[p.ID] = p
	return p, nil
}

func (s *Store) ListPlanItems(_ context.Context, coupleID, planID domain.ID) ([]domain.PlanItem, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, err := s.planOf(coupleID, planID); err != nil {
		return nil, err
	}
	var out []domain.PlanItem
	for _, it := range s.planItems {
		if it.PlanID == planID {
			out = append(out, it)
		}
	}
	slices.SortFunc(out, func(a, b domain.PlanItem) int { return strings.Compare(string(a.ID), string(b.ID)) })
	return out, nil
}

func (s *Store) AddPlanItem(_ context.Context, coupleID domain.ID, it domain.PlanItem) (domain.PlanItem, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, err := s.planOf(coupleID, it.PlanID); err != nil {
		return domain.PlanItem{}, err
	}
	it.ID = s.newID()
	s.planItems[it.ID] = it
	return it, nil
}

func (s *Store) UpdatePlanItem(_ context.Context, coupleID domain.ID, it domain.PlanItem) (domain.PlanItem, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	old, ok := s.planItems[it.ID]
	if !ok {
		return domain.PlanItem{}, ports.ErrNotFound
	}
	if _, err := s.planOf(coupleID, old.PlanID); err != nil {
		return domain.PlanItem{}, err
	}
	it.PlanID = old.PlanID
	s.planItems[it.ID] = it
	return it, nil
}

// --- PantryRepo ---

func (s *Store) GetPantry(_ context.Context, coupleID domain.ID) ([]domain.PantryItem, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return slices.Clone(s.pantry[coupleID]), nil
}

func (s *Store) ReplacePantry(_ context.Context, coupleID domain.ID, items []domain.PantryItem) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.pantry[coupleID] = slices.Clone(items)
	return nil
}

// --- CartRepo ---

func (s *Store) ListCartLines(_ context.Context, coupleID, planID domain.ID) ([]domain.CartLine, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, err := s.planOf(coupleID, planID); err != nil {
		return nil, err
	}
	var out []domain.CartLine
	for _, l := range s.cartLines {
		if l.PlanID == planID {
			out = append(out, l)
		}
	}
	slices.SortFunc(out, func(a, b domain.CartLine) int { return strings.Compare(string(a.ID), string(b.ID)) })
	return out, nil
}

func (s *Store) AddCartLine(_ context.Context, coupleID domain.ID, l domain.CartLine) (domain.CartLine, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, err := s.planOf(coupleID, l.PlanID); err != nil {
		return domain.CartLine{}, err
	}
	l.ID = s.newID()
	s.cartLines[l.ID] = l
	return l, nil
}

func (s *Store) UpdateCartLine(_ context.Context, coupleID domain.ID, l domain.CartLine) (domain.CartLine, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	old, ok := s.cartLines[l.ID]
	if !ok {
		return domain.CartLine{}, ports.ErrNotFound
	}
	if _, err := s.planOf(coupleID, old.PlanID); err != nil {
		return domain.CartLine{}, err
	}
	l.PlanID = old.PlanID
	s.cartLines[l.ID] = l
	return l, nil
}

func (s *Store) DeleteCartLine(_ context.Context, coupleID, lineID domain.ID) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	old, ok := s.cartLines[lineID]
	if !ok {
		return ports.ErrNotFound
	}
	if _, err := s.planOf(coupleID, old.PlanID); err != nil {
		return err
	}
	delete(s.cartLines, lineID)
	return nil
}

// --- PriceRepo ---

func (s *Store) MappedProducts(_ context.Context, ingredientIDs []domain.ID) (map[domain.ID][]domain.Product, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := map[domain.ID][]domain.Product{}
	for _, ing := range ingredientIDs {
		for _, pid := range s.mapping[ing] {
			out[ing] = append(out[ing], s.products[pid])
		}
	}
	return out, nil
}

func (s *Store) LatestPrices(_ context.Context, locationID domain.ID, productIDs []domain.ID) (map[domain.ID]domain.Price, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := map[domain.ID]domain.Price{}
	for _, p := range s.prices {
		if p.LocationID != locationID || !slices.Contains(productIDs, p.ProductID) {
			continue
		}
		if cur, ok := out[p.ProductID]; !ok || p.FetchedAt.After(cur.FetchedAt) {
			out[p.ProductID] = p
		}
	}
	return out, nil
}

// --- JobRepo ---

func (s *Store) EnqueueJob(_ context.Context, j domain.Job) (domain.Job, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	j.ID = s.newID()
	j.Status = domain.JobQueued
	if j.CreatedAt.IsZero() {
		j.CreatedAt = time.Now().UTC()
	}
	s.jobs[j.ID] = j
	return j, nil
}

func (s *Store) GetJob(_ context.Context, coupleID, jobID domain.ID) (domain.Job, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	j, ok := s.jobs[jobID]
	if !ok || j.CoupleID != coupleID {
		return domain.Job{}, ports.ErrNotFound
	}
	return j, nil
}
