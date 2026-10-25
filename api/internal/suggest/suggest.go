// Package suggest подбирает блюда по пожеланиям пары: пересечение голосов.
// Чистая функция без БД. Ранжирование «по вкусу» (рекомендации) — задача
// Python-части, здесь только простое правило.
package suggest

import (
	"sort"

	"github.com/aliss3046/cookingApp/api/internal/domain"
)

// Tier — насколько блюдо подходит паре.
type Tier string

const (
	// TierAll — блюдо хотят все участники пары.
	TierAll Tier = "all"
	// TierSome — хочет кто-то, остальные нейтральны или не голосовали.
	TierSome Tier = "some"
)

type Suggestion struct {
	RecipeID domain.ID
	Tier     Tier
	// WantedBy — участники, проголосовавшие «хочу».
	WantedBy []domain.ID
}

// Input — всё, что нужно подбору.
type Input struct {
	Recipes []domain.Recipe
	Votes   []domain.Vote
	// Members — участники пары (один или два). Голоса остальных игнорируются.
	Members []domain.ID
	// Planned — блюда, которые уже в плане; их не предлагаем.
	Planned map[domain.ID]bool
}

// Suggest возвращает блюда по правилам:
//   - предлагаются только подтверждённые блюда (черновики импорта нет);
//   - блюдо, за которое кто-то проголосовал «не хочу», не предлагается;
//   - нет голоса считается «нейтрально»;
//   - блюдо, которого никто не хочет, не предлагается;
//   - сначала TierAll (хотят все), затем TierSome; внутри уровня по названию.
func Suggest(in Input) []Suggestion {
	if len(in.Members) == 0 {
		return nil
	}
	member := map[domain.ID]bool{}
	for _, m := range in.Members {
		member[m] = true
	}
	votes := map[domain.ID]map[domain.ID]domain.VoteValue{} // recipe -> user -> value
	for _, v := range in.Votes {
		if !member[v.UserID] {
			continue
		}
		if votes[v.RecipeID] == nil {
			votes[v.RecipeID] = map[domain.ID]domain.VoteValue{}
		}
		votes[v.RecipeID][v.UserID] = v.Value
	}

	byID := map[domain.ID]domain.Recipe{}
	var out []Suggestion
	for _, r := range in.Recipes {
		if r.Status != domain.RecipeConfirmed || in.Planned[r.ID] {
			continue
		}
		s, ok := classify(votes[r.ID], in.Members)
		if !ok {
			continue
		}
		s.RecipeID = r.ID
		byID[r.ID] = r
		out = append(out, s)
	}

	sort.SliceStable(out, func(i, j int) bool {
		if out[i].Tier != out[j].Tier {
			return out[i].Tier == TierAll
		}
		ti, tj := byID[out[i].RecipeID].Title, byID[out[j].RecipeID].Title
		if ti != tj {
			return ti < tj
		}
		return out[i].RecipeID < out[j].RecipeID
	})
	return out
}

// classify определяет уровень блюда по голосам участников.
func classify(v map[domain.ID]domain.VoteValue, members []domain.ID) (Suggestion, bool) {
	var s Suggestion
	for _, m := range members {
		switch v[m] {
		case domain.VoteDontWant:
			return Suggestion{}, false
		case domain.VoteWant:
			s.WantedBy = append(s.WantedBy, m)
		}
	}
	switch {
	case len(s.WantedBy) == 0:
		return Suggestion{}, false
	case len(s.WantedBy) == len(members):
		s.Tier = TierAll
	default:
		s.Tier = TierSome
	}
	return s, true
}

// Conflict — участник пары, который проголосовал «не хочу» за блюдо.
type Conflict struct {
	UserID domain.ID
}

// Conflicts возвращает участников, не желающих это блюдо. Нужен для предупреждения
// при добавлении блюда в план и в списке плана (голос мог поменяться позже).
// Добавление не запрещается: решение за парой.
func Conflicts(recipeID domain.ID, votes []domain.Vote, members []domain.ID) []Conflict {
	var out []Conflict
	for _, m := range members {
		for _, v := range votes {
			if v.RecipeID == recipeID && v.UserID == m && v.Value == domain.VoteDontWant {
				out = append(out, Conflict{UserID: m})
				break
			}
		}
	}
	return out
}

// IsMatch — совпадение: блюдо хотят все участники пары и никто не против.
func IsMatch(recipeID domain.ID, votes []domain.Vote, members []domain.ID) bool {
	if len(members) == 0 {
		return false
	}
	byUser := map[domain.ID]domain.VoteValue{}
	for _, v := range votes {
		if v.RecipeID == recipeID {
			byUser[v.UserID] = v.Value
		}
	}
	s, ok := classify(byUser, members)
	return ok && s.Tier == TierAll
}
