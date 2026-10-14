package cart

import (
	"fmt"
	"math"
	"sort"

	"github.com/aliss3046/cookingApp/api/internal/domain"
)

const eps = 1e-9

func ceilEps(x float64) float64 { return math.Ceil(x - eps) }

func round2(x float64) float64 { return math.Round(x*100) / 100 }

// ErrUnknownRecipe — в плане есть блюдо, которого нет во входных данных.
type ErrUnknownRecipe struct{ ID domain.ID }

func (e ErrUnknownRecipe) Error() string { return fmt.Sprintf("cart: unknown recipe %q", e.ID) }

// buildNeeds выполняет шаги 1–5: порции, склейка, исключения, запасы, ручные позиции.
// Цены и товары здесь не нужны.
func buildNeeds(in Input) ([]Line, error) {
	needs := map[domain.ID]*Need{}
	var review []Line

	for _, item := range in.Plan {
		r, ok := in.Recipes[item.RecipeID]
		if !ok {
			return nil, ErrUnknownRecipe{ID: item.RecipeID}
		}
		for _, ri := range r.Ingredients {
			if ri.Optional {
				continue
			}
			if ri.NeedsReview || ri.IngredientID == nil || !ri.Unit.Valid() {
				review = append(review, Line{
					Title: ri.RawText, RawText: ri.RawText,
					Status: StatusNeedsReview, Cheapest: -1,
				})
				continue
			}
			if in.Excluded[*ri.IngredientID] {
				continue
			}
			add(needs, *ri.IngredientID, ri.QtyPerServing*float64(item.Servings), ri.Unit)
		}
	}

	// Ручные позиции с привязкой к ингредиенту склеиваются с потребностью по плану.
	// Исключение пары относится к позициям из плана и на них не действует.
	fromManual := map[domain.ID]*Need{}
	manualTitle := map[domain.ID]string{}
	var unlinked []domain.CartLine
	for _, m := range in.Manual {
		if m.IngredientID == nil || !m.Unit.Valid() {
			unlinked = append(unlinked, m)
			continue
		}
		id := *m.IngredientID
		add(needs, id, m.Qty, m.Unit)
		add(fromManual, id, m.Qty, m.Unit)
		if manualTitle[id] == "" {
			manualTitle[id] = m.Title
		}
	}

	// Количество, заданное парой, заменяет расчётное и запасами не уменьшается.
	overridden := map[domain.ID]bool{}
	for id, o := range in.QtyOverrides {
		n := needs[id]
		if n == nil || !o.Unit.Valid() {
			continue
		}
		*n = needFrom(math.Max(0, o.Qty), o.Unit)
		overridden[id] = true
	}

	subtractPantry(needs, in.Pantry, overridden)

	ids := make([]domain.ID, 0, len(needs))
	for id := range needs {
		ids = append(ids, id)
	}
	sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })

	lines := make([]Line, 0, len(ids)+len(review)+len(in.Manual))
	for _, id := range ids {
		id := id
		l := Line{
			IngredientID: &id, Title: in.Ingredients[id].Name,
			Need: *needs[id], Status: StatusOK, Cheapest: -1,
			QtyOverridden: overridden[id],
		}
		if l.Title == "" {
			l.Title = manualTitle[id]
		}
		if fm := fromManual[id]; fm != nil {
			l.FromManual = *fm
		}
		if l.Need.zero() {
			l.Status = StatusCovered
		}
		lines = append(lines, l)
	}
	lines = append(lines, review...)
	for _, m := range unlinked {
		lines = append(lines, Line{
			Title: m.Title, Manual: true, Status: StatusOK, Cheapest: -1,
			Need: needFrom(m.Qty, m.Unit),
		})
	}
	return lines, nil
}

// add прибавляет количество к потребности ингредиента: штуки отдельно,
// остальное (г и мл считаются равными) в массу.
func add(m map[domain.ID]*Need, id domain.ID, qty float64, unit domain.Unit) {
	n := m[id]
	if n == nil {
		n = &Need{}
		m[id] = n
	}
	d := needFrom(qty, unit)
	n.Mass += d.Mass
	n.Pcs += d.Pcs
}

func needFrom(qty float64, unit domain.Unit) Need {
	if unit == domain.UnitPiece {
		return Need{Pcs: qty}
	}
	return Need{Mass: qty}
}

// subtractPantry вычитает запасы: масса из массы, штуки из штук.
// Запас в другой единице не вычитается (ничего не пересчитываем молча).
// Ингредиенты с количеством, заданным парой, пропускаются.
func subtractPantry(needs map[domain.ID]*Need, pantry []domain.PantryItem, skip map[domain.ID]bool) {
	for _, p := range pantry {
		n := needs[p.IngredientID]
		if n == nil || skip[p.IngredientID] {
			continue
		}
		if p.Unit == domain.UnitPiece {
			n.Pcs = math.Max(0, n.Pcs-p.Qty)
		} else {
			n.Mass = math.Max(0, n.Mass-p.Qty)
		}
	}
}
