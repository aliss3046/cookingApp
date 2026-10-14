package cart

import (
	"time"

	"github.com/aliss3046/cookingApp/api/internal/domain"
)

// weightStepG — шаг заказа весового товара (0,1 кг).
const weightStepG = 100

// massTotal приводит потребность к массе. Штуки переводятся только через вес
// штуки из справочника, и тогда результат помечается estimated.
func massTotal(n Need, pieceWeight float64) (total float64, estimated, ok bool) {
	if n.Pcs > eps && pieceWeight <= 0 {
		return 0, false, false
	}
	return n.Mass + n.Pcs*pieceWeight, n.Pcs > eps, true
}

// pcsTotal приводит потребность к штукам (масса через вес штуки).
func pcsTotal(n Need, pieceWeight float64) (total float64, estimated, ok bool) {
	if n.Mass > eps && pieceWeight <= 0 {
		return 0, false, false
	}
	t := n.Pcs
	if n.Mass > eps {
		t += n.Mass / pieceWeight
	}
	return t, n.Mass > eps, true
}

// offerFor считает предложение одного товара. Исходная потребность не меняется.
func offerFor(p domain.Product, price *domain.Price, n Need, pieceWeight float64, now time.Time) Offer {
	o := Offer{
		ProductID: p.ID, StoreID: p.StoreID, Title: p.Title, Brand: p.Brand,
		Mode: p.SaleMode, Status: OfferOK,
	}
	if price == nil || (p.SaleMode != domain.SaleByWeight && price.Price <= 0) {
		o.Status = OfferNoPrice
		return o
	}
	o.InStock, o.StoreOnly = price.InStock, price.StoreOnly
	o.Stale, o.FetchedAt = price.Stale(now), price.FetchedAt

	switch p.SaleMode {
	case domain.SalePackMass:
		if p.PackQty <= 0 {
			o.Status = OfferInvalid
			return o
		}
		total, est, ok := massTotal(n, pieceWeight)
		if !ok {
			o.Status = OfferUnitMismatch
			return o
		}
		packs := ceilEps(total / p.PackQty)
		o.Qty, o.QtyUnit, o.Estimated = packs, "packs", est
		o.Cost = round2(packs * price.Price)
		o.Leftover, o.LeftoverUnit = packs*p.PackQty-total, p.PackUnit

	case domain.SaleByWeight:
		total, est, ok := massTotal(n, pieceWeight)
		if !ok {
			o.Status = OfferUnitMismatch
			return o
		}
		perKg, ok := pricePerKg(p, price)
		if !ok {
			o.Status = OfferNoPrice
			return o
		}
		grams := ceilEps(total/weightStepG) * weightStepG
		o.Qty, o.QtyUnit, o.Estimated = grams/1000, "kg", est
		o.Cost = round2(grams / 1000 * perKg)

	case domain.SalePerPiece:
		total, est, ok := pcsTotal(n, pieceWeight)
		if !ok {
			o.Status = OfferUnitMismatch
			return o
		}
		pcs := ceilEps(total)
		o.Qty, o.QtyUnit, o.Estimated = pcs, "pcs", est
		o.Cost = round2(pcs * price.Price)

	case domain.SalePackCount:
		if p.PackQty <= 0 {
			o.Status = OfferInvalid
			return o
		}
		total, est, ok := pcsTotal(n, pieceWeight)
		if !ok {
			o.Status = OfferUnitMismatch
			return o
		}
		packs := ceilEps(total / p.PackQty)
		o.Qty, o.QtyUnit, o.Estimated = packs, "packs", est
		o.Cost = round2(packs * price.Price)
		o.Leftover, o.LeftoverUnit = packs*p.PackQty-total, domain.UnitPiece

	default:
		o.Status = OfferInvalid
	}
	return o
}

// pricePerKg берёт цену за кг; если её нет, выводит из цены упаковки.
func pricePerKg(p domain.Product, price *domain.Price) (float64, bool) {
	if price.PricePerKg != nil && *price.PricePerKg > 0 {
		return *price.PricePerKg, true
	}
	if p.SaleMode == domain.SaleByWeight && p.PackQty > 0 && price.Price > 0 {
		return price.Price / p.PackQty * 1000, true
	}
	return 0, false
}
