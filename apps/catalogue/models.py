from django.db import models
from django.utils.text import slugify
from django.contrib.auth import get_user_model
User=get_user_model()

class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="subcategories"
    )
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="categories/", blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    sku = models.CharField(max_length=60, unique=True, db_index=True)
    hsn_code = models.CharField(max_length=20, blank=True)
    brand = models.CharField(max_length=100, blank=True)

    short_description = models.CharField(max_length=300, blank=True)
    description = models.TextField()
    specifications = models.JSONField(default=list, blank=True)

    # Dual Pricing (Section 3.8) & GST (Section 3.6)
    customer_price = models.DecimalField(max_digits=10, decimal_places=2)
    dealer_price = models.DecimalField(max_digits=10, decimal_places=2)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=18.00)

    # Inventory & Warranty (Sections 3.7 & 3.12)
    stock_quantity = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=5)
    warranty_months = models.PositiveIntegerField(default=12)

    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            self.slug = f"{base_slug}-{self.sku.lower()}"
        super().save(*args, **kwargs)

    @property
    def in_stock(self) -> bool:
        return self.stock_quantity > 0

    @property
    def is_low_stock(self) -> bool:
        return 0 < self.stock_quantity <= self.low_stock_threshold

    def __str__(self):
        return f"{self.name} ({self.sku})"


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="products/images/")
    alt_text = models.CharField(max_length=150, blank=True)
    is_primary = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "display_order", "id"]

    def save(self, *args, **kwargs):
        if self.is_primary:
            ProductImage.objects.filter(product=self.product, is_primary=True).exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)


class ProductVideo(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="videos")
    title = models.CharField(max_length=150)
    video_url = models.URLField(blank=True)
    video_file = models.FileField(upload_to="products/videos/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class InventoryLog(models.Model):
    """
    Immutable audit ledger for every stock change (Section 3.7).
    """

    class TransactionType(models.TextChoices):
        OPENING_STOCK = "OPENING_STOCK", "Opening Stock"
        RESTOCK = "RESTOCK", "Purchase / Restock (+)"
        ORDER_DEDUCT = "ORDER_DEDUCT", "Order Placed (-)"
        ORDER_RESTORE = "ORDER_RESTORE", "Order Cancelled / Returned (+)"
        ADJUSTMENT = "ADJUSTMENT", "Manual Adjustment (+/-)"
        DAMAGED = "DAMAGED", "Damaged / Write-off (-)"
        EXCEL_IMPORT = "EXCEL_IMPORT", "Bulk Excel Sync"

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="inventory_logs"
    )
    transaction_type = models.CharField(
        max_length=20, choices=TransactionType.choices, db_index=True
    )
    quantity_change = models.IntegerField(
        help_text="Positive for stock added, negative for stock deducted."
    )
    stock_before = models.PositiveIntegerField()
    stock_after = models.PositiveIntegerField()
    reference_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="Order number, PO number, or Excel batch reference.",
    )
    notes = models.CharField(max_length=255, blank=True)
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_actions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        sign = "+" if self.quantity_change > 0 else ""
        return f"{self.product.sku} | {self.transaction_type} ({sign}{self.quantity_change})"