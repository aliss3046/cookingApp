package cart

import (
	"sort"

	"github.com/aliss3046/cookingApp/api/internal/domain"
)

// Build собирает корзину: потребность по плану, предложения магазинов с учётом
// выбранной марки и сравнение, где дешевле. Чистая функция.
func Build(in Input) (Cart, error) {
	lines, err := buildNeeds(in)
	if err != nil {
		return Cart{}, err
	}
	for i := range lines {
		l := &lines[i]
		if l.IngredientID == nil || l.Status != StatusOK {
			continue
		}
		fillOffers(l, in)
	}
	c := Cart{Lines: lines}
	c.Totals, c.Recommendation = compare(lines)
	return c, nil
}

// fillOffers считает предложения строки и применяет правила выбора марки.
func fillOffers(l *Line, in Input) {
	id := *l.IngredientID
	products := in.Catalog[id]
	if len(products) == 0 {
		l.Status = StatusNoOffers
		return
	}
	pw := 0.0
	if ing, ok := in.Ingredients[id]; ok && ing.PieceWeightG != nil {
		pw = *ing.PieceWeightG
	}

	all := make([]Offer, len(products))
	brands := map[string]bool{}
	for i, p := range products {
		var price *domain.Price
		if pr, ok := in.Prices[p.ID]; ok {
			price = &pr
		}
		all[i] = offerFor(p, price, l.Need, pw, in.Now)
		brands[p.Brand] = true
	}

	// Закреплённый товар задаёт и марку: он точнее сохранённого выбора марки.
	// Если товара уже нет в каталоге, закрепление игнорируется.
	var chosen *domain.Product
	for i := range products {
		if products[i].ID == in.ChosenProducts[id] {
			chosen = &products[i]
		}
	}

	pref := in.BrandPrefs[id]
	switch {
	case chosen != nil:
		l.Brand = chosen.Brand
	case pref != "" && brands[pref]:
		l.Brand = pref
	case pref == "" && len(brands) == 1:
		for b := range brands {
			l.Brand = b
		}
		l.BrandAuto = true
	default:
		// марок несколько и выбора нет, либо сохранённой марки нигде нет
		l.Status = StatusChooseBrand
		l.BrandOptions = brandOptions(all)
		return
	}

	l.Offers = offersForBrand(all, l.Brand)
	if chosen != nil {
		l.Offers = pinChosen(l.Offers, *chosen)
	}
	hasOK := false
	for _, o := range l.Offers {
		if o.Status == OfferOK {
			hasOK = true
		}
	}
	if !hasOK {
		l.Status = StatusNoOffers
	}
	sortOffers(l.Offers)
	l.Cheapest = cheapestIndex(l.Offers)
}

// pinChosen закрепляет товар: в его магазине остаётся только он, остальные
// магазины не меняются. Закреплённое предложение получает флаг Chosen.
func pinChosen(os []Offer, chosen domain.Product) []Offer {
	out := os[:0:0]
	for _, o := range os {
		if o.StoreID == chosen.StoreID && o.ProductID != chosen.ID {
			continue
		}
		o.Chosen = o.ProductID == chosen.ID
		out = append(out, o)
	}
	return out
}

// offersForBrand оставляет предложения выбранной марки. В магазине, где её нет,
// добавляется самая дешёвая другая марка, помеченная Alternative.
func offersForBrand(all []Offer, brand string) []Offer {
	var out []Offer
	haveBrand := map[domain.ID]bool{}
	for _, o := range all {
		if o.Brand == brand {
			out = append(out, o)
			haveBrand[o.StoreID] = true
		}
	}
	alt := map[domain.ID]*Offer{}
	for i := range all {
		o := all[i]
		if haveBrand[o.StoreID] || o.Status != OfferOK {
			continue
		}
		if cur := alt[o.StoreID]; cur == nil || betterThan(o, *cur) {
			alt[o.StoreID] = &o
		}
	}
	for _, o := range alt {
		o.Alternative = true
		out = append(out, *o)
	}
	return out
}

// brandOptions — по одной записи на марку с минимальной ценой среди подходящих предложений.
func brandOptions(all []Offer) []BrandOption {
	byBrand := map[string]*BrandOption{}
	for _, o := range all {
		opt := byBrand[o.Brand]
		if opt == nil {
			opt = &BrandOption{Brand: o.Brand}
			byBrand[o.Brand] = opt
		}
		if !o.eligible() {
			continue
		}
		if !opt.HasPrice || o.Cost < opt.MinCost {
			opt.MinCost, opt.HasPrice = o.Cost, true
		}
	}
	out := make([]BrandOption, 0, len(byBrand))
	for _, opt := range byBrand {
		out = append(out, *opt)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Brand < out[j].Brand })
	return out
}

// betterThan: точная оценка лучше приблизительной, затем дешевле, затем по id.
func betterThan(a, b Offer) bool {
	if a.Estimated != b.Estimated {
		return !a.Estimated
	}
	if a.Cost != b.Cost {
		return a.Cost < b.Cost
	}
	return a.ProductID < b.ProductID
}

// sortOffers: подходящие вперёд (по betterThan), затем остальные, альтернативы последними.
func sortOffers(os []Offer) {
	rank := func(o Offer) int {
		switch {
		case o.Alternative:
			return 2
		case o.eligible():
			return 0
		default:
			return 1
		}
	}
	sort.SliceStable(os, func(i, j int) bool {
		ri, rj := rank(os[i]), rank(os[j])
		if ri != rj {
			return ri < rj
		}
		return betterThan(os[i], os[j])
	})
}

// cheapestIndex возвращает индекс самого дешёвого подходящего предложения
// (точные оценки раньше приблизительных) или -1. os уже отсортирован.
func cheapestIndex(os []Offer) int {
	for i, o := range os {
		if o.eligible() {
			return i
		}
	}
	return -1
}

// compare считает итоги по магазинам и рекомендацию. В сравнении участвуют строки
// со статусом ok и выбранной маркой; ручные, непроверенные и без марки — нет.
func compare(lines []Line) ([]StoreTotal, Recommendation) {
	var rec Recommendation
	totals := map[domain.ID]*StoreTotal{}
	var resolved []int
	for i, l := range lines {
		if l.IngredientID == nil || l.Status != StatusOK {
			continue
		}
		resolved = append(resolved, i)
		for _, o := range l.Offers {
			if totals[o.StoreID] == nil {
				totals[o.StoreID] = &StoreTotal{StoreID: o.StoreID}
			}
		}
	}

	for _, i := range resolved {
		l := lines[i]
		// Offers отсортированы (sortOffers), поэтому первое подходящее
		// предложение магазина по этой строке и есть лучшее.
		best := map[domain.ID]Offer{}
		for _, o := range l.Offers {
			if _, seen := best[o.StoreID]; !seen && o.eligible() {
				best[o.StoreID] = o
			}
		}
		for storeID, t := range totals {
			o, ok := best[storeID]
			if !ok {
				t.Missing++
				continue
			}
			t.Covered++
			t.Total = round2(t.Total + o.Cost)
			t.HasEstimated = t.HasEstimated || o.Estimated
			t.HasStale = t.HasStale || o.Stale
		}
		if l.Cheapest >= 0 {
			o := l.Offers[l.Cheapest]
			rec.Split.Picks = append(rec.Split.Picks, Pick{
				LineIndex: i, StoreID: o.StoreID, ProductID: o.ProductID, Cost: o.Cost,
			})
			rec.Split.Total = round2(rec.Split.Total + o.Cost)
		} else {
			rec.Split.Uncovered++
		}
	}

	out := make([]StoreTotal, 0, len(totals))
	for _, t := range totals {
		out = append(out, *t)
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Missing != out[j].Missing {
			return out[i].Missing < out[j].Missing
		}
		if out[i].Total != out[j].Total {
			return out[i].Total < out[j].Total
		}
		return out[i].StoreID < out[j].StoreID
	})
	if len(out) > 0 && out[0].Missing == 0 {
		best := out[0]
		rec.SingleStore = &best
	}
	return out, rec
}

// ApplyLines переносит сохранённые строки корзины во вход расчёта:
// ручные позиции, исключения, заданное количество и закреплённые товары.
func (in *Input) ApplyLines(lines []domain.CartLine) {
	for _, l := range lines {
		if l.AddedManually {
			if !l.Excluded {
				in.Manual = append(in.Manual, l)
			}
		} else if l.IngredientID != nil && l.Excluded {
			if in.Excluded == nil {
				in.Excluded = map[domain.ID]bool{}
			}
			in.Excluded[*l.IngredientID] = true
		}
		if l.IngredientID == nil {
			continue
		}
		if l.QtyOverridden && !l.AddedManually {
			if in.QtyOverrides == nil {
				in.QtyOverrides = map[domain.ID]QtyOverride{}
			}
			in.QtyOverrides[*l.IngredientID] = QtyOverride{Qty: l.Qty, Unit: l.Unit}
		}
		if l.ChosenProductID != nil {
			if in.ChosenProducts == nil {
				in.ChosenProducts = map[domain.ID]domain.ID{}
			}
			in.ChosenProducts[*l.IngredientID] = *l.ChosenProductID
		}
	}
}
