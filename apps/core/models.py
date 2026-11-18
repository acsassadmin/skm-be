from django.db import models

class Contact(models.Model):
    full_name = models.CharField(max_length=150)
    email_address = models.EmailField()
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Contact Message'
        verbose_name_plural = 'Contact Messages'

    def __str__(self):
        return f"{self.full_name} ({self.email_address})"


class Enquiry(models.Model):
    REFERRAL_CHOICES = [
        ('google', 'Google / Search Engine'),
        ('social_media', 'Social Media'),
        ('referral', 'Friend / Colleague Referral'),
        ('advertisement', 'Online Advertisement'),
        ('other', 'Other'),
    ]

    SUBJECT_CHOICES = [
        ('product_enquiry', 'Product enquiry'),
        ('custom_engineering_project', 'Custom engineering project'),
        ('training_internship', 'Training / internship'),
        ('institutional_collaboration', 'Institutional collaboration'),
        ('service_maintenance', 'Service & maintenance'),
        ('other', 'Other'),
    ]

    full_name = models.CharField(max_length=150)
    email_address = models.EmailField()
    phone_number = models.CharField(max_length=20)
    company_name = models.CharField(
        max_length=200, 
        blank=True, 
        help_text="Optional: Company or Organization Name"
    )
    subject = models.CharField(
        max_length=100,
        choices=SUBJECT_CHOICES,
    )
    message = models.TextField()
    how_did_you_hear_about_us = models.CharField(
        max_length=50,
        choices=REFERRAL_CHOICES,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Enquiry'
        verbose_name_plural = 'Enquiries'

    def __str__(self):
        return f"{self.subject} - {self.full_name}"
