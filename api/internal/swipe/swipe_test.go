package swipe_test

import (
	"errors"
	"fmt"
	"reflect"
	"sort"
	"testing"

	"github.com/aliss3046/cookingApp/api/internal/domain"
	"github.com/aliss3046/cookingApp/api/internal/swipe"
)

const (
	anna  domain.ID = "anna"
	boris domain.ID = "boris"
)

var members = []domain.ID{anna, boris}

func recipes(n int) []domain.Recipe {
	var rs []domain.Recipe
	for i := 0; i < n; i++ {
		rs = append(rs, domain.Recipe{
			ID: domain.ID(fmt.Sprintf("r%02d", i)), Title: fmt.Sprintf("Блюдо %d", i), Status: domain.RecipeActive,
		})
	}
	return rs
}

func ids(rs []domain.Recipe) []domain.ID {
	var out []domain.ID
	for _, r := range rs {
		out = append(out, r.ID)
	}
	return out
}

func vote(r string, u domain.ID, v domain.VoteValue) domain.Vote {
	return domain.Vote{RecipeID: domain.ID(r), UserID: u, Value: v}
}

// allPages проходит колоду страницами и возвращает все карточки по порядку.
func allPages(t *testing.T, in swipe.DeckInput) []domain.ID {
	t.Helper()
	var out []domain.ID
	for pages := 0; pages < 100; pages++ {
		d, err := swipe.BuildDeck(in)
		if err != nil {
			t.Fatal(err)
		}
		out = append(out, ids(d.Cards)...)
		if d.NextCursor == "" {
			return out
		}
		in.Cursor = d.NextCursor
	}
	t.Fatal("deck does not end")
	return nil
}

func TestDeckPagesCoverEveryCardOnce(t *testing.T) {
	in := swipe.DeckInput{Recipes: recipes(11), Me: anna, Members: members, Limit: 3}
	got := allPages(t, in)

	if len(got) != 11 {
		t.Fatalf("want 11 cards, got %d: %v", len(got), got)
	}
	seen := map[domain.ID]bool{}
	for _, id := range got {
		if seen[id] {
			t.Fatalf("duplicate card %s", id)
		}
		seen[id] = true
	}
	// порядок стабилен между запросами
	if again := allPages(t, in); !reflect.DeepEqual(got, again) {
		t.Fatalf("order must be stable:\n%v\n%v", got, again)
	}
	// и не зависит от размера страницы
	in.Limit = 4
	if other := allPages(t, in); !reflect.DeepEqual(got, other) {
		t.Fatalf("order must not depend on page size:\n%v\n%v", got, other)
	}
}

func TestDeckExcludesVotedDraftAndRejectedByPartner(t *testing.T) {
	rs := recipes(6)
	rs[4].Status = domain.RecipeDraft
	in := swipe.DeckInput{
		Recipes: rs, Me: anna, Members: members,
		Votes: []domain.Vote{
			vote("r00", anna, domain.VoteWant),           // я уже голосовал
			vote("r01", anna, domain.VoteNeutral),        // нейтральный голос тоже голос
			vote("r02", boris, domain.VoteDontWant),      // партнёр отклонил
			vote("r03", boris, domain.VoteWant),          // партнёр хочет: показываем
			vote("r05", "stranger", domain.VoteDontWant), // не из этой пары: игнорируем
		},
	}
	got := allPages(t, in)
	sort.Slice(got, func(i, j int) bool { return got[i] < got[j] })
	want := []domain.ID{"r03", "r05"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestDeckCursorSurvivesVoting(t *testing.T) {
	in := swipe.DeckInput{Recipes: recipes(9), Me: anna, Members: members, Limit: 3}
	first, err := swipe.BuildDeck(in)
	if err != nil {
		t.Fatal(err)
	}
	full := allPages(t, in)

	// пользователь проголосовал за карточки первой страницы и за одну из второй
	for _, c := range first.Cards {
		in.Votes = append(in.Votes, vote(string(c.ID), anna, domain.VoteWant))
	}
	in.Votes = append(in.Votes, vote(string(full[4]), anna, domain.VoteDontWant))

	in.Cursor = first.NextCursor
	rest := allPages(t, in)
	want := append(append([]domain.ID{}, full[3:4]...), full[5:]...)
	if !reflect.DeepEqual(rest, want) {
		t.Fatalf("got %v, want %v", rest, want)
	}
}

func TestDeckLimits(t *testing.T) {
	in := swipe.DeckInput{Recipes: recipes(60), Me: anna, Members: members}
	d, err := swipe.BuildDeck(in)
	if err != nil || len(d.Cards) != swipe.DefaultLimit || d.NextCursor == "" {
		t.Fatalf("default limit: %d cards, cursor %q, err %v", len(d.Cards), d.NextCursor, err)
	}
	in.Limit = 1000
	if d, _ = swipe.BuildDeck(in); len(d.Cards) != swipe.MaxLimit {
		t.Fatalf("limit must be capped at %d, got %d", swipe.MaxLimit, len(d.Cards))
	}
	in.Limit = -5
	if d, _ = swipe.BuildDeck(in); len(d.Cards) != swipe.DefaultLimit {
		t.Fatalf("negative limit falls back to default, got %d", len(d.Cards))
	}
	// ровно по размеру страницы: следующей страницы нет
	in = swipe.DeckInput{Recipes: recipes(3), Me: anna, Members: members, Limit: 3}
	if d, _ = swipe.BuildDeck(in); len(d.Cards) != 3 || d.NextCursor != "" {
		t.Fatalf("last page: %d cards, cursor %q", len(d.Cards), d.NextCursor)
	}
	// пустая колода
	if d, _ = swipe.BuildDeck(swipe.DeckInput{Me: anna}); len(d.Cards) != 0 || d.NextCursor != "" {
		t.Fatalf("empty deck expected, got %+v", d)
	}
}

func TestDeckBadCursor(t *testing.T) {
	for _, c := range []string{"garbage", "zz:r01", "0000000000000001:", ":r01"} {
		_, err := swipe.BuildDeck(swipe.DeckInput{Recipes: recipes(2), Me: anna, Cursor: c})
		if !errors.Is(err, swipe.ErrBadCursor) {
			t.Errorf("cursor %q: want ErrBadCursor, got %v", c, err)
		}
	}
}

func TestDeckOrderDiffersBetweenUsers(t *testing.T) {
	a := allPages(t, swipe.DeckInput{Recipes: recipes(20), Me: anna, Members: members})
	b := allPages(t, swipe.DeckInput{Recipes: recipes(20), Me: boris, Members: members})
	if reflect.DeepEqual(a, b) {
		t.Fatal("different users should get different order")
	}
}

func TestDeckDuplicateRecipeKeepsPaging(t *testing.T) {
	// блюдо, пришедшее дважды (одинаковые ключ и id), не должно ломать курсор
	rs := recipes(2)
	rs = append(rs, rs[0])
	got := allPages(t, swipe.DeckInput{Recipes: rs, Me: anna, Members: members, Limit: 1})
	if len(got) == 0 {
		t.Fatalf("deck must not be empty: %v", got)
	}
}

func TestNormalizeVotes(t *testing.T) {
	got, err := swipe.NormalizeVotes(anna, []swipe.VoteInput{
		{RecipeID: "a", Value: domain.VoteWant},
		{RecipeID: "b", Value: domain.VoteDontWant},
		{RecipeID: "a", Value: domain.VoteDontWant}, // последний голос за блюдо побеждает
	})
	if err != nil {
		t.Fatal(err)
	}
	want := []domain.Vote{vote("a", anna, domain.VoteDontWant), vote("b", anna, domain.VoteDontWant)}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %+v, want %+v", got, want)
	}

	tooMany := make([]swipe.VoteInput, swipe.MaxBatch+1)
	for i := range tooMany {
		tooMany[i] = swipe.VoteInput{RecipeID: domain.ID(fmt.Sprint(i)), Value: domain.VoteWant}
	}
	bad := [][]swipe.VoteInput{
		nil,
		tooMany,
		{{RecipeID: "a", Value: "maybe"}},
		{{RecipeID: "", Value: domain.VoteWant}},
	}
	for i, items := range bad {
		if _, err := swipe.NormalizeVotes(anna, items); !errors.Is(err, swipe.ErrBadBatch) {
			t.Errorf("case %d: want ErrBadBatch, got %v", i, err)
		}
	}
	if _, err := swipe.NormalizeVotes(anna, tooMany[:swipe.MaxBatch]); err != nil {
		t.Errorf("exactly MaxBatch votes must be accepted: %v", err)
	}
}

func TestResultsMatch(t *testing.T) {
	existing := []domain.Vote{
		vote("a", boris, domain.VoteWant),
		vote("b", boris, domain.VoteDontWant),
		vote("c", anna, domain.VoteDontWant), // старый голос заменяется новым
		vote("c", boris, domain.VoteWant),
		vote("e", boris, domain.VoteWant),
	}
	applied := []domain.Vote{
		vote("a", anna, domain.VoteWant),    // партнёр тоже хочет: совпало
		vote("b", anna, domain.VoteWant),    // партнёр против: нет
		vote("c", anna, domain.VoteWant),    // переголосовал: совпало
		vote("d", anna, domain.VoteWant),    // партнёр не голосовал: нет
		vote("e", anna, domain.VoteNeutral), // не «хочу»: не совпадение
	}
	got := swipe.Results(applied, existing, members)
	want := []bool{true, false, true, false, false}
	for i, r := range got {
		if r.Match != want[i] || r.Vote != applied[i] {
			t.Errorf("result %d: %+v, want match=%v", i, r, want[i])
		}
	}
}
