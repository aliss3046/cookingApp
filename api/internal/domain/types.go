// Package domain содержит доменные типы API. Источник правды для полей —
// docs/openapi.yaml и docs/schema.md.
package domain

import "time"

// ID — UUID в строковом виде. Генерирует база.
type ID string

// Unit — базовая единица количества. Пересчёт из «ст. ложек» делается до записи в базу.
type Unit string

const (
	UnitGram  Unit = "g"
	UnitMl    Unit = "ml"
	UnitPiece Unit = "pcs"
)

func (u Unit) Valid() bool {
	switch u {
	case UnitGram, UnitMl, UnitPiece:
		return true
	}
	return false
}

type RecipeStatus string

const (
	RecipeDraft     RecipeStatus = "draft"
	RecipeConfirmed RecipeStatus = "confirmed"
)

type VoteValue string

const (
	VoteWant     VoteValue = "want"
	VoteNeutral  VoteValue = "neutral"
	VoteDontWant VoteValue = "dont_want"
)

type Ingredient struct {
	ID            ID
	Name          string
	Synonyms      []string
	Group         string
	DensityGPerMl *float64
	PieceWeightG  *float64
}

type RecipeIngredient struct {
	IngredientID  *ID // nil, если строка не разобрана
	QtyPerServing float64
	Unit          Unit
	Optional      bool
	RawText       string
	NeedsReview   bool
}

type Recipe struct {
	ID              ID
	CoupleID        *ID // nil — общее блюдо
	Title           string
	DefaultServings int
	SourceURL       string
	Tags            []string
	Status          RecipeStatus
	Ingredients     []RecipeIngredient
}

type Vote struct {
	RecipeID ID
	UserID   ID
	Value    VoteValue
}

type Plan struct {
	ID        ID
	CoupleID  ID
	WeekStart time.Time
	Status    string
}

type PlanItem struct {
	ID       ID
	PlanID   ID
	RecipeID ID
	Servings int
	Date     *time.Time
}

type PantrySource string

const (
	PantryManual   PantrySource = "manual"
	PantryLeftover PantrySource = "leftover"
)

type PantryItem struct {
	IngredientID ID
	Qty          float64
	Unit         Unit
	Source       PantrySource
}

type CartLine struct {
	ID            ID
	PlanID        ID
	IngredientID  *ID // nil для ручной позиции
	Title         string
	Qty           float64
	Unit          Unit
	Excluded      bool
	AddedManually bool
	// QtyOverridden — пара сама задала количество; оно заменяет расчётное по плану.
	QtyOverridden bool
	// ChosenProductID — товар, закреплённый парой в его магазине.
	ChosenProductID *ID
}

// SaleMode — как магазин продаёт товар. Определяет парсер.
type SaleMode string

const (
	SalePackMass  SaleMode = "pack_mass"  // упаковка фиксированной массы/объёма
	SalePackCount SaleMode = "pack_count" // упаковка из N штук
	SalePerPiece  SaleMode = "per_piece"  // любое целое число штук
	SaleByWeight  SaleMode = "by_weight"  // на вес, цена за кг
)

type Product struct {
	ID         ID
	StoreID    ID
	ExternalID string
	Title      string
	Brand      string // пусто — марка не определена
	SaleMode   SaleMode
	PackQty    float64 // pack_mass: г/мл в упаковке; pack_count: штук в упаковке
	PackUnit   Unit
	Category   string
}

type PriceSource string

const (
	PriceFromSite    PriceSource = "site"
	PriceFromManual  PriceSource = "manual"
	PriceFromReceipt PriceSource = "receipt"
)

// Price — одна запись истории цен. Цены только добавляются.
type Price struct {
	ProductID  ID
	LocationID ID
	Price      float64
	CardPrice  *float64
	PricePerKg *float64
	InStock    bool
	StoreOnly  bool
	FetchedAt  time.Time
	Source     PriceSource
}

// PriceStaleAfter — цена старше этого считается устаревшей и помечается, а не скрывается.
const PriceStaleAfter = 72 * time.Hour

func (p Price) Stale(now time.Time) bool {
	return now.Sub(p.FetchedAt) > PriceStaleAfter
}

type JobKind string

const (
	JobQuote  JobKind = "quote"
	JobImport JobKind = "import"
)

type JobStatus string

const (
	JobQueued  JobStatus = "queued"
	JobRunning JobStatus = "running"
	JobDone    JobStatus = "done"
	JobFailed  JobStatus = "failed"
)

type Job struct {
	ID         ID
	CoupleID   ID
	Kind       JobKind
	Status     JobStatus
	Params     map[string]any
	Result     map[string]any
	Error      string
	CreatedAt  time.Time
	FinishedAt *time.Time
}
