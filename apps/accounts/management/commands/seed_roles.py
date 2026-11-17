from django.core.management.base import BaseCommand
from accounts.models import Role


class Command(BaseCommand):
    help = "Seeds default RBAC roles for SKM Electronics"

    def handle(self, *args, **kwargs):
        default_roles = [
            {"name": "Admin", "code": "ADMIN", "requires_approval": True},
            {"name": "Customer", "code": "CUSTOMER", "requires_approval": False},
            {"name": "Dealer", "code": "DEALER", "requires_approval": True},
            {"name": "Student", "code": "STUDENT", "requires_approval": False},
            {"name": "Faculty", "code": "FACULTY", "requires_approval": True},
        ]
        for item in default_roles:
            role, created = Role.objects.get_or_create(
                code=item["code"],
                defaults=item,
            )
            status = "Created" if created else "Already exists"
            self.stdout.write(f"{status}: {role}")
