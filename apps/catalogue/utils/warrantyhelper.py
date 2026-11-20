import calendar
from datetime import date
from django.utils import timezone
from catalogue.models import Warranty, WarrantyClaim


def add_months(start_date: date, months: int) -> date:
    """Adds `months` calendar months to `start_date`, clamping end-of-month days cleanly."""
    if months <= 0:
        return start_date

    month_zero_based = (start_date.month - 1) + months
    year = start_date.year + (month_zero_based // 12)
    month = (month_zero_based % 12) + 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(start_date.day, max_day)
    return date(year, month, day)


def calculate_warranty_end_date(start_date: date, warranty_months: int) -> date:
    """Computes warranty expiration date from start_date and warranty_months."""
    return add_months(start_date, warranty_months)


def is_warranty_active(warranty: Warranty, as_of_date: date | None = None) -> bool:
    """Checks whether a warranty is active on `as_of_date` (defaults to today)."""
    check_date = as_of_date or timezone.localdate()
    if warranty.status == Warranty.Status.VOID:
        return False
    return warranty.start_date <= check_date <= warranty.end_date


def sync_warranty_expiry(warranty: Warranty, as_of_date: date | None = None) -> Warranty:
    """Marks an ACTIVE warranty as EXPIRED if past end_date; leaves VOID/CLAIMED untouched."""
    check_date = as_of_date or timezone.localdate()
    if warranty.status == Warranty.Status.ACTIVE and check_date > warranty.end_date:
        warranty.status = Warranty.Status.EXPIRED
        warranty.save(update_fields=["status", "updated_at"])
    return warranty


def create_warranty_for_product(
    product,
    start_date: date | None = None,
    order_item=None,
    serial_number: str = "",
    warranty_months: int | None = None,
) -> Warranty:
    """Creates a Warranty record using `product.warranty_months` by default."""
    effective_start = start_date or timezone.localdate()
    months = warranty_months if warranty_months is not None else product.warranty_months
    end_date = calculate_warranty_end_date(effective_start, months)

    return Warranty.objects.create(
        order_item=order_item,
        product=product,
        serial_number=serial_number,
        warranty_months=months,
        start_date=effective_start,
        end_date=end_date,
        status=Warranty.Status.ACTIVE,
    )


def resolve_warranty_claim(
    claim: WarrantyClaim,
    resolution: str,
    replacement_serial: str = "",
    mark_warranty_claimed: bool = False,
) -> WarrantyClaim:
    """Updates claim resolution/status and optionally updates serial or warranty status."""
    claim.resolution = resolution
    claim.status = WarrantyClaim.Status.RESOLVED
    claim.resolved_at = timezone.now()

    if replacement_serial:
        claim.replacement_serial = replacement_serial
        if resolution == WarrantyClaim.Resolution.REPLACED:
            claim.warranty.serial_number = replacement_serial
            claim.warranty.save(update_fields=["serial_number", "updated_at"])

    if mark_warranty_claimed and claim.warranty.status == Warranty.Status.ACTIVE:
        claim.warranty.status = Warranty.Status.CLAIMED
        claim.warranty.save(update_fields=["status", "updated_at"])

    claim.save(
        update_fields=[
            "resolution",
            "status",
            "resolved_at",
            "replacement_serial",
        ]
    )
    return claim