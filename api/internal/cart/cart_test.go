package cart_test

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/aliss3046/cookingApp/api/internal/cart"
	"github.com/aliss3046/cookingApp/api/internal/domain"
)

var now = time.Date(2026, 10, 13, 12, 0, 0, 0, time.UTC)

// fixture — вход сценария в компактном виде; expect — ожидаемая проекция результата.
type fixture struct {
	Name        string `json:"name"`
	Ingredients []struct {
		ID     string  `json:"id"`
		Name   string  `json:"name"`
		PieceG float64 `json:"piece_g"`
	} `json:"ingredients"`
	Recipes []struct {
		ID    string `json:"id"`
		Items []struct {
			Ing      string  `json:"ing"`
			Qty      float64 `json:"qty"`
			Unit     string  `json:"unit"`
			Optional bool    `json:"optional"`
			Review   bool    `json:"review"`
			Raw      string  `json:"raw"`
		} `json:"items"`
	} `json:"recipes"`
	Plan []struct {
		Recipe   string `json:"recipe"`
		Servings int    `json:"servings"`
	} `json:"plan"`
	Pantry []struct {
		Ing  string  `json:"ing"`
		Qty  float64 `json:"qty"`
		Unit string  `json:"unit"`
	} `json:"pantry"`
	Excluded []string `json:"excluded"`
	Manual   []struct {
		Title string  `json:"title"`
		Ing   string  `json:"ing"`
		Qty   float64 `json:"qty"`
		Unit  string  `json:"unit"`
	} `json:"manual"`
	Overrides []struct {
		Ing  string  `json:"ing"`
		Qty  float64 `json:"qty"`
		Unit string  `json:"unit"`
	} `json:"overrides"`
	Chosen   map[string]string `json:"chosen"`
	Products []struct {
		ID        string  `json:"id"`
		Store     string  `json:"store"`
		Ing       string  `json:"ing"`
		Brand     string  `json:"brand"`
		Mode      string  `json:"mode"`
		Pack      float64 `json:"pack"`
		Unit      string  `json:"unit"`
		Price     float64 `json:"price"`
		PerKg     float64 `json:"per_kg"`
		NoPrice   bool    `json:"no_price"`
		OOS       bool    `json:"oos"`
		StoreOnly bool    `json:"store_only"`
		AgeH      float64 `json:"age_h"`
	} `json:"products"`
	Prefs  map[string]string `json:"prefs"`
	Expect result            `json:"expect"`
}

type result struct {
	Error  string     `json:"error,omitempty"`
	Lines  []lineOut  `json:"lines,omitempty"`
	Totals []totalOut `json:"totals,omitempty"`
	Single string     `json:"single,omitempty"`
	Split  *splitOut  `json:"split,omitempty"`
}

type lineOut struct {
	Key        string     `json:"key"`
	Status     string     `json:"status"`
	Mass       float64    `json:"mass,omitempty"`
	Pcs        float64    `json:"pcs,omitempty"`
	Overridden bool       `json:"overridden,omitempty"`
	ManMass    float64    `json:"man_mass,omitempty"`
	ManPcs     float64    `json:"man_pcs,omitempty"`
	Brand      string     `json:"brand,omitempty"`
	BrandAuto  bool       `json:"brand_auto,omitempty"`
	Brands     []string   `json:"brands,omitempty"`
	Cheapest   string     `json:"cheapest,omitempty"`
	Offers     []offerOut `json:"offers,omitempty"`
}

type offerOut struct {
	P      string   `json:"p"`
	Status string   `json:"status"`
	Qty    float64  `json:"qty,omitempty"`
	Unit   string   `json:"unit,omitempty"`
	Cost   float64  `json:"cost,omitempty"`
	Left   float64  `json:"left,omitempty"`
	Flags  []string `json:"flags,omitempty"`
}

type totalOut struct {
	Store   string  `json:"store"`
	Total   float64 `json:"total,omitempty"`
	Covered int     `json:"covered,omitempty"`
	Missing int     `json:"missing,omitempty"`
	Est     bool    `json:"est,omitempty"`
	Stale   bool    `json:"stale,omitempty"`
}

type splitOut struct {
	Total     float64  `json:"total,omitempty"`
	Uncovered int      `json:"uncovered,omitempty"`
	Picks     []string `json:"picks,omitempty"`
}

func r3(x float64) float64 { return math.Round(x*1000) / 1000 }

func (f fixture) input() cart.Input {
	in := cart.Input{
		Recipes:     map[domain.ID]domain.Recipe{},
		Ingredients: map[domain.ID]domain.Ingredient{},
		Excluded:    map[domain.ID]bool{},
		Catalog:     map[domain.ID][]domain.Product{},
		Prices:      map[domain.ID]domain.Price{},
		BrandPrefs:  map[domain.ID]string{},
		Now:         now,
	}
	for _, i := range f.Ingredients {
		ing := domain.Ingredient{ID: domain.ID(i.ID), Name: i.Name}
		if i.PieceG > 0 {
			pg := i.PieceG
			ing.PieceWeightG = &pg
		}
		in.Ingredients[ing.ID] = ing
	}
	for _, r := range f.Recipes {
		rec := domain.Recipe{ID: domain.ID(r.ID)}
		for _, it := range r.Items {
			ri := domain.RecipeIngredient{
				QtyPerServing: it.Qty, Unit: domain.Unit(it.Unit),
				Optional: it.Optional, NeedsReview: it.Review, RawText: it.Raw,
			}
			if it.Ing != "" {
				id := domain.ID(it.Ing)
				ri.IngredientID = &id
			}
			rec.Ingredients = append(rec.Ingredients, ri)
		}
		in.Recipes[rec.ID] = rec
	}
	for _, p := range f.Plan {
		in.Plan = append(in.Plan, domain.PlanItem{RecipeID: domain.ID(p.Recipe), Servings: p.Servings})
	}
	for _, p := range f.Pantry {
		in.Pantry = append(in.Pantry, domain.PantryItem{
			IngredientID: domain.ID(p.Ing), Qty: p.Qty, Unit: domain.Unit(p.Unit),
		})
	}
	for _, e := range f.Excluded {
		in.Excluded[domain.ID(e)] = true
	}
	for _, m := range f.Manual {
		l := domain.CartLine{Title: m.Title, Qty: m.Qty, Unit: domain.Unit(m.Unit), AddedManually: true}
		if m.Ing != "" {
			id := domain.ID(m.Ing)
			l.IngredientID = &id
		}
		in.Manual = append(in.Manual, l)
	}
	if len(f.Overrides) > 0 {
		in.QtyOverrides = map[domain.ID]cart.QtyOverride{}
	}
	for _, o := range f.Overrides {
		in.QtyOverrides[domain.ID(o.Ing)] = cart.QtyOverride{Qty: o.Qty, Unit: domain.Unit(o.Unit)}
	}
	if len(f.Chosen) > 0 {
		in.ChosenProducts = map[domain.ID]domain.ID{}
	}
	for ing, p := range f.Chosen {
		in.ChosenProducts[domain.ID(ing)] = domain.ID(p)
	}
	for _, p := range f.Products {
		prod := domain.Product{
			ID: domain.ID(p.ID), StoreID: domain.ID(p.Store), Title: p.ID, Brand: p.Brand,
			SaleMode: domain.SaleMode(p.Mode), PackQty: p.Pack, PackUnit: domain.Unit(p.Unit),
		}
		ing := domain.ID(p.Ing)
		in.Catalog[ing] = append(in.Catalog[ing], prod)
		if p.NoPrice {
			continue
		}
		age := p.AgeH
		if age == 0 {
			age = 1
		}
		pr := domain.Price{
			ProductID: prod.ID, Price: p.Price, InStock: !p.OOS, StoreOnly: p.StoreOnly,
			FetchedAt: now.Add(-time.Duration(age * float64(time.Hour))),
		}
		if p.PerKg > 0 {
			pk := p.PerKg
			pr.PricePerKg = &pk
		}
		in.Prices[prod.ID] = pr
	}
	for k, v := range f.Prefs {
		in.BrandPrefs[domain.ID(k)] = v
	}
	return in
}

func project(c cart.Cart) result {
	var out result
	for _, l := range c.Lines {
		lo := lineOut{
			Status: string(l.Status), Mass: r3(l.Need.Mass), Pcs: r3(l.Need.Pcs),
			Brand: l.Brand, BrandAuto: l.BrandAuto, Overridden: l.QtyOverridden,
			ManMass: r3(l.FromManual.Mass), ManPcs: r3(l.FromManual.Pcs),
		}
		if l.IngredientID != nil {
			lo.Key = string(*l.IngredientID)
		} else {
			lo.Key = l.Title
		}
		for _, b := range l.BrandOptions {
			if b.HasPrice {
				lo.Brands = append(lo.Brands, fmt.Sprintf("%s=%.2f", b.Brand, b.MinCost))
			} else {
				lo.Brands = append(lo.Brands, b.Brand+"=-")
			}
		}
		if l.Cheapest >= 0 {
			lo.Cheapest = string(l.Offers[l.Cheapest].ProductID)
		}
		for _, o := range l.Offers {
			oo := offerOut{
				P: string(o.ProductID), Status: string(o.Status),
				Qty: r3(o.Qty), Unit: o.QtyUnit, Cost: o.Cost, Left: r3(o.Leftover),
			}
			if o.Status == cart.OfferOK {
				for flag, on := range map[string]bool{
					"estimated": o.Estimated, "stale": o.Stale, "oos": !o.InStock,
					"store_only": o.StoreOnly, "alternative": o.Alternative, "chosen": o.Chosen,
				} {
					if on {
						oo.Flags = append(oo.Flags, flag)
					}
				}
				sort.Strings(oo.Flags)
			}
			lo.Offers = append(lo.Offers, oo)
		}
		out.Lines = append(out.Lines, lo)
	}
	for _, t := range c.Totals {
		out.Totals = append(out.Totals, totalOut{
			Store: string(t.StoreID), Total: t.Total, Covered: t.Covered, Missing: t.Missing,
			Est: t.HasEstimated, Stale: t.HasStale,
		})
	}
	if c.Recommendation.SingleStore != nil {
		out.Single = string(c.Recommendation.SingleStore.StoreID)
	}
	sp := c.Recommendation.Split
	if sp.Total != 0 || sp.Uncovered != 0 || len(sp.Picks) > 0 {
		so := &splitOut{Total: sp.Total, Uncovered: sp.Uncovered}
		for _, p := range sp.Picks {
			so.Picks = append(so.Picks, string(p.ProductID))
		}
		out.Split = so
	}
	return out
}

func mustJSON(t *testing.T, v any) []byte {
	t.Helper()
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func TestFixtures(t *testing.T) {
	files, err := filepath.Glob("testdata/*.json")
	if err != nil || len(files) < 15 {
		t.Fatalf("need at least 15 fixtures, got %d (%v)", len(files), err)
	}
	for _, file := range files {
		file := file
		t.Run(strings.TrimSuffix(filepath.Base(file), ".json"), func(t *testing.T) {
			raw, err := os.ReadFile(file)
			if err != nil {
				t.Fatal(err)
			}
			var f fixture
			if err := json.Unmarshal(raw, &f); err != nil {
				t.Fatal(err)
			}
			c, err := cart.Build(f.input())
			if f.Expect.Error != "" {
				if err == nil || !strings.Contains(err.Error(), f.Expect.Error) {
					t.Fatalf("want error containing %q, got %v", f.Expect.Error, err)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			got, want := mustJSON(t, project(c)), mustJSON(t, f.Expect)
			if !bytes.Equal(got, want) {
				t.Fatalf("%s\n--- got ---\n%s\n--- want ---\n%s", f.Name, got, want)
			}
		})
	}
}
