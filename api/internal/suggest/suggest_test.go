package suggest_test

import (
	"reflect"
	"testing"

	"github.com/aliss3046/cookingApp/api/internal/domain"
	"github.com/aliss3046/cookingApp/api/internal/suggest"
)

const (
	anna  domain.ID = "anna"
	boris domain.ID = "boris"
	other domain.ID = "other-couple-user"
)

func recipe(id, title string) domain.Recipe {
	return domain.Recipe{ID: domain.ID(id), Title: title, Status: domain.RecipeConfirmed}
}

func vote(r string, u domain.ID, v domain.VoteValue) domain.Vote {
	return domain.Vote{RecipeID: domain.ID(r), UserID: u, Value: v}
}

type row struct {
	ID   domain.ID
	Tier suggest.Tier
	By   []domain.ID
}

func rows(ss []suggest.Suggestion) []row {
	var out []row
	for _, s := range ss {
		out = append(out, row{s.RecipeID, s.Tier, s.WantedBy})
	}
	return out
}

func TestSuggest(t *testing.T) {
	draft := recipe("draft", "Черновик")
	draft.Status = domain.RecipeDraft

	tests := []struct {
		name string
		in   suggest.Input
		want []row
	}{
		{
			name: "нет участников — пусто",
			in:   suggest.Input{Recipes: []domain.Recipe{recipe("a", "А")}},
			want: nil,
		},
		{
			name: "никто не голосовал — ничего не предлагаем",
			in: suggest.Input{
				Recipes: []domain.Recipe{recipe("a", "А")}, Members: []domain.ID{anna, boris},
			},
			want: nil,
		},
		{
			name: "хотят оба — выше, чем хочет один; нейтральные и без голоса — как нейтрально",
			in: suggest.Input{
				Recipes: []domain.Recipe{recipe("one", "Борщ"), recipe("both", "Плов"), recipe("neutral", "Суп")},
				Votes: []domain.Vote{
					vote("one", anna, domain.VoteWant), vote("one", boris, domain.VoteNeutral),
					vote("both", anna, domain.VoteWant), vote("both", boris, domain.VoteWant),
					vote("neutral", anna, domain.VoteNeutral),
				},
				Members: []domain.ID{anna, boris},
			},
			want: []row{
				{"both", suggest.TierAll, []domain.ID{anna, boris}},
				{"one", suggest.TierSome, []domain.ID{anna}},
			},
		},
		{
			name: "«не хочу» от любого исключает блюдо, даже если второй хочет",
			in: suggest.Input{
				Recipes: []domain.Recipe{recipe("a", "А"), recipe("b", "Б")},
				Votes: []domain.Vote{
					vote("a", anna, domain.VoteWant), vote("a", boris, domain.VoteDontWant),
					vote("b", anna, domain.VoteDontWant),
				},
				Members: []domain.ID{anna, boris},
			},
			want: nil,
		},
		{
			name: "черновики и блюда из плана не предлагаются",
			in: suggest.Input{
				Recipes: []domain.Recipe{draft, recipe("planned", "Уже в плане"), recipe("ok", "Новое")},
				Votes: []domain.Vote{
					vote("draft", anna, domain.VoteWant), vote("planned", anna, domain.VoteWant),
					vote("ok", anna, domain.VoteWant),
				},
				Members: []domain.ID{anna, boris},
				Planned: map[domain.ID]bool{"planned": true},
			},
			want: []row{{"ok", suggest.TierSome, []domain.ID{anna}}},
		},
		{
			name: "голоса не из этой пары игнорируются",
			in: suggest.Input{
				Recipes: []domain.Recipe{recipe("a", "А")},
				Votes: []domain.Vote{
					vote("a", other, domain.VoteWant), vote("a", boris, domain.VoteDontWant),
				},
				Members: []domain.ID{anna, boris},
			},
			want: nil,
		},
		{
			name: "в паре один участник: его «хочу» значит «хотят все»",
			in: suggest.Input{
				Recipes: []domain.Recipe{recipe("a", "А")},
				Votes:   []domain.Vote{vote("a", anna, domain.VoteWant)},
				Members: []domain.ID{anna},
			},
			want: []row{{"a", suggest.TierAll, []domain.ID{anna}}},
		},
		{
			name: "порядок: сначала хотят все, внутри уровня по названию, затем по id",
			in: suggest.Input{
				Recipes: []domain.Recipe{
					recipe("z", "Яблоки"), recipe("y", "Блины"), recipe("x", "Блины"), recipe("w", "Арбуз"),
				},
				Votes: []domain.Vote{
					vote("z", anna, domain.VoteWant), vote("z", boris, domain.VoteWant),
					vote("y", anna, domain.VoteWant), vote("y", boris, domain.VoteWant),
					vote("x", anna, domain.VoteWant), vote("x", boris, domain.VoteWant),
					vote("w", anna, domain.VoteWant),
				},
				Members: []domain.ID{anna, boris},
			},
			want: []row{
				{"x", suggest.TierAll, []domain.ID{anna, boris}},
				{"y", suggest.TierAll, []domain.ID{anna, boris}},
				{"z", suggest.TierAll, []domain.ID{anna, boris}},
				{"w", suggest.TierSome, []domain.ID{anna}},
			},
		},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got := rows(suggest.Suggest(tc.in))
			if !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("\n got: %+v\nwant: %+v", got, tc.want)
			}
		})
	}
}

func TestIsMatch(t *testing.T) {
	votes := []domain.Vote{
		vote("both", anna, domain.VoteWant), vote("both", boris, domain.VoteWant),
		vote("one", anna, domain.VoteWant),
		vote("veto", anna, domain.VoteWant), vote("veto", boris, domain.VoteDontWant),
	}
	members := []domain.ID{anna, boris}
	tests := []struct {
		recipe  string
		members []domain.ID
		want    bool
	}{
		{"both", members, true},
		{"one", members, false},
		{"veto", members, false},
		{"none", members, false},
		{"one", []domain.ID{anna}, true}, // в паре один участник
		{"both", nil, false},
	}
	for _, tc := range tests {
		if got := suggest.IsMatch(domain.ID(tc.recipe), votes, tc.members); got != tc.want {
			t.Errorf("%s with %v: got %v, want %v", tc.recipe, tc.members, got, tc.want)
		}
	}
}

func TestConflicts(t *testing.T) {
	votes := []domain.Vote{
		vote("a", anna, domain.VoteDontWant),
		vote("a", boris, domain.VoteWant),
		vote("b", anna, domain.VoteWant),
		vote("b", boris, domain.VoteDontWant),
		vote("c", anna, domain.VoteDontWant),
		vote("c", boris, domain.VoteDontWant),
		vote("c", boris, domain.VoteDontWant), // повтор не удваивает
		vote("d", other, domain.VoteDontWant), // чужая пара
	}
	members := []domain.ID{anna, boris}
	tests := []struct {
		recipe string
		want   []suggest.Conflict
	}{
		{"a", []suggest.Conflict{{UserID: anna}}},
		{"b", []suggest.Conflict{{UserID: boris}}},
		{"c", []suggest.Conflict{{UserID: anna}, {UserID: boris}}},
		{"d", nil},
		{"unknown", nil},
	}
	for _, tc := range tests {
		got := suggest.Conflicts(domain.ID(tc.recipe), votes, members)
		if !reflect.DeepEqual(got, tc.want) {
			t.Errorf("recipe %s: got %+v, want %+v", tc.recipe, got, tc.want)
		}
	}
}
