from pydantic import BaseModel, Field

from app.settings import MAX_PURCHASE_QUANTITY


class Product(BaseModel):
    id: str
    name: str
    category: str
    price_pence: int


class PurchaseRequest(BaseModel):
    product_id: str
    quantity: int = Field(ge=1, le=MAX_PURCHASE_QUANTITY)


class Purchase(BaseModel):
    id: str
    product_id: str
    quantity: int
    status: str
