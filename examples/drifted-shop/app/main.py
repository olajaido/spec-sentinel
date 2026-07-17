from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, status

from app.inventory import reserve_inventory
from app.models import Product, Purchase, PurchaseRequest
from app.settings import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.webhooks import fire_purchase_webhook

app = FastAPI(title="Drifted Shop", version="0.1.0")

PRODUCTS = {
    "prod_coffee": Product(
        id="prod_coffee", name="Coffee Beans", category="grocery", price_pence=1299
    ),
    "prod_mug": Product(id="prod_mug", name="Blue Mug", category="home", price_pence=1599),
}
PURCHASES: dict[str, Purchase] = {}


@app.get("/v1/health", status_code=status.HTTP_200_OK)
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/products", response_model=list[Product])
def list_products(
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> list[Product]:
    return list(PRODUCTS.values())[:page_size]


@app.get("/v1/products/{product_id}", response_model=Product)
def get_product(product_id: str) -> Product:
    product = PRODUCTS.get(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.post("/v1/purchases", response_model=Purchase, status_code=status.HTTP_201_CREATED)
def create_purchase(request: PurchaseRequest) -> Purchase:
    if request.product_id not in PRODUCTS:
        raise HTTPException(status_code=404, detail="Product not found")
    if not reserve_inventory(request.product_id, request.quantity):
        raise HTTPException(status_code=409, detail="Insufficient inventory")
    purchase = Purchase(
        id=f"pur_{uuid4().hex[:12]}",
        product_id=request.product_id,
        quantity=request.quantity,
        status="created",
    )
    PURCHASES[purchase.id] = purchase
    fire_purchase_webhook(purchase.id)
    return purchase


@app.get("/v1/purchases/{purchase_id}", response_model=Purchase)
def get_purchase(purchase_id: str) -> Purchase:
    purchase = PURCHASES.get(purchase_id)
    if purchase is None:
        raise HTTPException(status_code=404, detail="Purchase not found")
    return purchase


@app.patch("/v1/purchases/{purchase_id}/cancel", response_model=Purchase)
def cancel_purchase(purchase_id: str) -> Purchase:
    purchase = get_purchase(purchase_id)
    purchase.status = "cancelled"
    return purchase


@app.delete("/v1/purchases/{purchase_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_purchase(purchase_id: str) -> None:
    if PURCHASES.pop(purchase_id, None) is None:
        raise HTTPException(status_code=404, detail="Purchase not found")


@app.get("/v1/categories", response_model=list[str])
def list_categories() -> list[str]:
    return sorted({product.category for product in PRODUCTS.values()})


@app.get("/v1/stats")
def stats() -> dict[str, int]:
    return {"products": len(PRODUCTS), "purchases": len(PURCHASES)}


@app.post("/v1/webhooks/test", status_code=status.HTTP_202_ACCEPTED)
def test_webhook() -> dict[str, str]:
    return {"status": "queued"}
