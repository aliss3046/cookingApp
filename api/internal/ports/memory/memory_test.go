package memory_test

import (
	"testing"

	"github.com/aliss3046/cookingApp/api/internal/domain"
	"github.com/aliss3046/cookingApp/api/internal/ports/contracttest"
	"github.com/aliss3046/cookingApp/api/internal/ports/memory"
)

func TestContract(t *testing.T) {
	contracttest.Run(t, func(t *testing.T) contracttest.Env {
		s := memory.New()
		e := contracttest.Env{
			Repos:   s,
			CoupleA: "couple-a", UserA1: "user-a1", UserA2: "user-a2",
			CoupleB: "couple-b", UserB1: "user-b1",
		}
		s.SeedMember(e.CoupleA, e.UserA1)
		s.SeedMember(e.CoupleA, e.UserA2)
		s.SeedMember(e.CoupleB, e.UserB1)
		e.SharedRecipeID = s.SeedSharedRecipe(domain.Recipe{
			Title: "Омлет", DefaultServings: 1, Status: domain.RecipeActive,
		}).ID
		return e
	})
}
