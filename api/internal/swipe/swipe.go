// Package swipe — логика выбора блюд свайпами: колода карточек, пачка голосов
// и признак «совпало». Чистые функции без БД.
package swipe

import (
	"errors"
	"fmt"
	"hash/fnv"
	"sort"
	"strconv"
	"strings"

	"github.com/aliss3046/cookingApp/api/internal/domain"
	"github.com/aliss3046/cookingApp/api/internal/suggest"
)

const (
	DefaultLimit = 20
	MaxLimit     = 50
	// MaxBatch — максимум голосов в одном запросе.
	MaxBatch = 100
)

var (
	ErrBadCursor = errors.New("swipe: invalid cursor")
	ErrBadBatch  = errors.New("swipe: invalid vote batch")
)

type DeckInput struct {
	// Recipes — блюда, видимые паре (общие и свои); фильтрует вызывающий код.
	Recipes []domain.Recipe
	// Votes — голоса обоих участников пары.
	Votes   []domain.Vote
	Me      domain.ID
	Members []domain.ID
	// Cursor — next_cursor предыдущей страницы; пусто для первой.
	Cursor string
	Limit  int
}

type Deck struct {
	Cards []domain.Recipe
	// NextCursor пуст, когда карточки закончились.
	NextCursor string
}

// BuildDeck возвращает следующую страницу колоды. В неё попадают подтверждённые
// блюда, за которые я ещё не голосовал и которые не отклонил партнёр (с его
// «не хочу» блюдо всё равно не попадёт в подборку).
//
// Порядок псевдослучайный, но стабильный для пользователя: карточки не прыгают
// между запросами, а голосование не сбивает курсор, потому что курсор — это позиция
// в порядке, а не номер страницы. «Пропустить» ничего не сохраняет: клиент сам
// откладывает карточку.
func BuildDeck(in DeckInput) (Deck, error) {
	limit := in.Limit
	switch {
	case limit <= 0:
		limit = DefaultLimit
	case limit > MaxLimit:
		limit = MaxLimit
	}
	after, err := parseCursor(in.Cursor)
	if err != nil {
		return Deck{}, err
	}

	voted := map[domain.ID]bool{}
	rejected := map[domain.ID]bool{}
	for _, v := range in.Votes {
		if v.UserID == in.Me {
			voted[v.RecipeID] = true
		} else if v.Value == domain.VoteDontWant && isMember(in.Members, v.UserID) {
			rejected[v.RecipeID] = true
		}
	}

	type card struct {
		pos    position
		recipe domain.Recipe
	}
	var cards []card
	for _, r := range in.Recipes {
		if r.Status != domain.RecipeActive || voted[r.ID] || rejected[r.ID] {
			continue
		}
		p := position{key: orderKey(in.Me, r.ID), id: r.ID}
		if after != nil && !p.after(*after) {
			continue
		}
		cards = append(cards, card{pos: p, recipe: r})
	}
	sort.Slice(cards, func(i, j int) bool { return cards[i].pos.less(cards[j].pos) })

	var d Deck
	for i, c := range cards {
		if i == limit {
			d.NextCursor = formatCursor(cards[i-1].pos)
			break
		}
		d.Cards = append(d.Cards, c.recipe)
	}
	return d, nil
}

func isMember(members []domain.ID, u domain.ID) bool {
	for _, m := range members {
		if m == u {
			return true
		}
	}
	return false
}

// position — место карточки в порядке колоды.
type position struct {
	key uint64
	id  domain.ID
}

func (p position) less(o position) bool {
	if p.key != o.key {
		return p.key < o.key
	}
	return p.id < o.id
}

func (p position) after(o position) bool { return o.less(p) }

func orderKey(me, recipe domain.ID) uint64 {
	h := fnv.New64a()
	_, _ = h.Write([]byte(string(me) + "/" + string(recipe)))
	return h.Sum64()
}

func formatCursor(p position) string {
	return fmt.Sprintf("%016x:%s", p.key, p.id)
}

func parseCursor(c string) (*position, error) {
	if c == "" {
		return nil, nil
	}
	hexKey, id, ok := strings.Cut(c, ":")
	if !ok || id == "" {
		return nil, ErrBadCursor
	}
	key, err := strconv.ParseUint(hexKey, 16, 64)
	if err != nil {
		return nil, ErrBadCursor
	}
	return &position{key: key, id: domain.ID(id)}, nil
}

// VoteInput — один свайп из запроса.
type VoteInput struct {
	RecipeID domain.ID
	Value    domain.VoteValue
}

// NormalizeVotes проверяет пачку голосов и превращает её в голоса пользователя.
// Если за одно блюдо в пачке несколько голосов, действует последний.
func NormalizeVotes(me domain.ID, items []VoteInput) ([]domain.Vote, error) {
	if len(items) == 0 {
		return nil, fmt.Errorf("%w: empty", ErrBadBatch)
	}
	if len(items) > MaxBatch {
		return nil, fmt.Errorf("%w: more than %d votes", ErrBadBatch, MaxBatch)
	}
	index := map[domain.ID]int{}
	var out []domain.Vote
	for _, it := range items {
		switch it.Value {
		case domain.VoteWant, domain.VoteNeutral, domain.VoteDontWant:
		default:
			return nil, fmt.Errorf("%w: unknown value %q", ErrBadBatch, it.Value)
		}
		if it.RecipeID == "" {
			return nil, fmt.Errorf("%w: empty recipe id", ErrBadBatch)
		}
		v := domain.Vote{RecipeID: it.RecipeID, UserID: me, Value: it.Value}
		if i, seen := index[it.RecipeID]; seen {
			out[i] = v
			continue
		}
		index[it.RecipeID] = len(out)
		out = append(out, v)
	}
	return out, nil
}

// Result — применённый голос и признак совпадения для ответа на свайп.
type Result struct {
	Vote  domain.Vote
	Match bool
}

// Results считает совпадения после применения голосов: голос «хочу», после
// которого блюдо хотят все участники пары. existing — голоса пары до запроса.
func Results(applied, existing []domain.Vote, members []domain.ID) []Result {
	merged := make([]domain.Vote, 0, len(existing)+len(applied))
	replaced := map[[2]domain.ID]bool{}
	for _, v := range applied {
		replaced[[2]domain.ID{v.RecipeID, v.UserID}] = true
	}
	for _, v := range existing {
		if !replaced[[2]domain.ID{v.RecipeID, v.UserID}] {
			merged = append(merged, v)
		}
	}
	merged = append(merged, applied...)

	out := make([]Result, len(applied))
	for i, v := range applied {
		out[i] = Result{
			Vote:  v,
			Match: v.Value == domain.VoteWant && suggest.IsMatch(v.RecipeID, merged, members),
		}
	}
	return out
}
