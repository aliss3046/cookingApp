// Package cart считает корзину: потребность по плану, предложения магазинов
// и сравнение, где дешевле. Только чистые функции: без БД, сети и времени
// (текущее время приходит в Input). Правила — docs/cart-edge-cases.md.
package cart

import (
	"time"

	"github.com/aliss3046/cookingApp/api/internal/domain"
)

// Input — всё, что нужно расчёту. Данные загружает вызывающий код через порты.
type Input struct {
	Plan        []domain.PlanItem
	Recipes     map[domain.ID]domain.Recipe
	Ingredients map[domain.ID]domain.Ingredient
	Pantry      []domain.PantryItem
	// Excluded — ингредиенты, которые пара убрала из корзины.
	Excluded map[domain.ID]bool
	// Manual — продукты, добавленные вручную. Если у строки задан IngredientID,
	// она склеивается с ингредиентом корзины и получает предложения магазинов.
	Manual []domain.CartLine
	// QtyOverrides — количество, заданное парой вместо расчётного (запасы не применяются).
	QtyOverrides map[domain.ID]QtyOverride
	// ChosenProducts — товар, закреплённый парой по ингредиенту.
	ChosenProducts map[domain.ID]domain.ID
	// Catalog — товары магазинов, сопоставленные ингредиентам.
	Catalog map[domain.ID][]domain.Product
	// Prices — последняя цена товара по адресу пары.
	Prices map[domain.ID]domain.Price
	// BrandPrefs — выбранная парой марка по ингредиенту.
	BrandPrefs map[domain.ID]string
	Now        time.Time
}

// QtyOverride — количество, которое пара задала сама.
type QtyOverride struct {
	Qty  float64
	Unit domain.Unit
}

// Need — потребность в тех единицах, в которых её задал рецепт.
// Масса (г и мл считаются равными) и штуки хранятся раздельно.
type Need struct {
	Mass float64
	Pcs  float64
}

func (n Need) zero() bool { return n.Mass <= eps && n.Pcs <= eps }

type LineStatus string

const (
	StatusOK          LineStatus = "ok"
	StatusCovered     LineStatus = "covered"      // запасов хватает
	StatusNeedsReview LineStatus = "needs_review" // строка рецепта не разобрана
	StatusNoOffers    LineStatus = "no_offers"    // нет товаров или ни у одного нет цены
	StatusChooseBrand LineStatus = "choose_brand" // паре надо выбрать марку
)

type Line struct {
	IngredientID *domain.ID
	Title        string
	RawText      string // для needs_review
	Manual       bool   // ручная позиция без привязки к ингредиенту: без цен и сравнения
	Need         Need
	Status       LineStatus
	// QtyOverridden — Need задан парой, а не посчитан по плану.
	QtyOverridden bool
	// FromManual — часть Need, добавленная вручную (для подсказки «из них вручную»).
	FromManual Need

	// Brand — марка, по которой построены предложения.
	Brand string
	// BrandAuto — марка выбрана автоматически (в магазинах она единственная);
	// вызывающий код может сохранить её как выбор пары.
	BrandAuto bool
	// BrandOptions заполнен при choose_brand.
	BrandOptions []BrandOption

	Offers []Offer
	// Cheapest — индекс самого дешёвого предложения в Offers, -1 если нет.
	Cheapest int
}

type BrandOption struct {
	Brand string
	// MinCost — минимальная стоимость среди подходящих предложений марки;
	// HasPrice=false, если посчитать нельзя.
	MinCost  float64
	HasPrice bool
}

type OfferStatus string

const (
	OfferOK           OfferStatus = "ok"
	OfferUnitMismatch OfferStatus = "unit_mismatch" // нет веса штуки для пересчёта
	OfferNoPrice      OfferStatus = "no_price"
	OfferInvalid      OfferStatus = "invalid_product" // у товара нет размера упаковки
)

type Offer struct {
	ProductID domain.ID
	StoreID   domain.ID
	Title     string
	Brand     string
	Mode      domain.SaleMode
	Status    OfferStatus

	// Qty — сколько покупать в единицах QtyUnit: "packs", "pcs" или "kg".
	Qty     float64
	QtyUnit string
	Cost    float64
	// Leftover — остаток после округления до упаковки; предлагается в запасы.
	Leftover     float64
	LeftoverUnit domain.Unit

	// Estimated — стоимость по оценке через вес штуки из справочника.
	Estimated bool
	Stale     bool
	InStock   bool
	StoreOnly bool
	// Chosen — товар закреплён парой в этом магазине.
	Chosen bool
	// Alternative — другая марка в магазине, где выбранной нет.
	Alternative bool
	FetchedAt   time.Time
}

// eligible — предложение можно считать «купить здесь».
func (o Offer) eligible() bool {
	return o.Status == OfferOK && o.InStock && !o.StoreOnly && !o.Alternative
}

type StoreTotal struct {
	StoreID domain.ID
	Total   float64
	// Covered — строк, которые магазин закрывает; Missing — не закрывает.
	Covered      int
	Missing      int
	HasEstimated bool
	HasStale     bool
}

type Pick struct {
	LineIndex int
	StoreID   domain.ID
	ProductID domain.ID
	Cost      float64
}

// Split — «разнести по магазинам»: по каждой строке самое дешёвое.
type Split struct {
	Total     float64
	Picks     []Pick
	Uncovered int // строк, для которых нет подходящего предложения
}

type Recommendation struct {
	// SingleStore — самый дешёвый магазин, закрывающий всю корзину; nil, если такого нет.
	SingleStore *StoreTotal
	Split       Split
}

type Cart struct {
	Lines []Line
	// Totals отсортированы: сначала полностью покрывающие корзину, затем по цене.
	Totals         []StoreTotal
	Recommendation Recommendation
}
