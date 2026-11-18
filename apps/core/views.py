from django.shortcuts import render
from rest_framework.views import APIView
from utils.responses import success_response,error_response
from rest_framework import status
from .models import Contact, Enquiry
from rest_framework.permissions import AllowAny, IsAdminUser
from .serializers import ContactSerializer, EnquirySerializer
# from utils import success_response, error_response
from utils.responses import success_response, error_response
from utils.filters import apply_search_and_filters
class HealthApiView(APIView):
    def get(self,request):
        return success_response(message="Everything works!!!",status_code=status.HTTP_200_OK)

class ContactAPIView(APIView):
    # def get_permissions(self):
    #     # Allow anyone to submit the form (POST), restrict GET and DELETE to admins
    #     if self.request.method == 'POST':
    #         return [AllowAny()]
    #     return [IsAdminUser()]

    def get(self, request, *args, **kwargs):
        contact_id = request.query_params.get('id')

        if contact_id:
            try:
                contact = Contact.objects.get(pk=contact_id)
            except (Contact.DoesNotExist, ValueError):
                return error_response(
                    message="Contact message not found.",
                    status_code=status.HTTP_404_NOT_FOUND
                )
            serializer = ContactSerializer(contact)
            return success_response(
                data=serializer.data,
                message="Contact message retrieved successfully."
            )

        contacts = Contact.objects.all()
        contacts = apply_search_and_filters(
            queryset=contacts,
            request=request,
            search_fields=('full_name','email_address','message')
        )
        serializer = ContactSerializer(contacts, many=True)
        return success_response(
            data=serializer.data,
            message="Contact messages retrieved successfully."
        )

    def post(self, request, *args, **kwargs):
        serializer = ContactSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return success_response(
                data=serializer.data,
                message="Your message has been sent successfully.",
                status_code=status.HTTP_201_CREATED
            )
        return error_response(
            errors=serializer.errors,
            message="Please correct the errors below.",
            status_code=status.HTTP_400_BAD_REQUEST
        )

    def put(self, request, *args, **kwargs):
        contact_id = request.query_params.get('id')

        if not contact_id:
            return error_response(
                message="Query parameter 'id' is required for update.",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        try:
            contact = Contact.objects.get(pk=contact_id)
        except (Contact.DoesNotExist, ValueError):
            return error_response(
                message="Contact message not found.",
                status_code=status.HTTP_404_NOT_FOUND
            )

        serializer = ContactSerializer(contact, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return success_response(
                data=serializer.data,
                message="Contact message updated successfully.",
                status_code=status.HTTP_200_OK
            )
        return error_response(
            errors=serializer.errors,
            message="Please correct the errors below.",
            status_code=status.HTTP_400_BAD_REQUEST
        )

    def delete(self, request, *args, **kwargs):
        contact_id = request.query_params.get('id')

        if not contact_id:
            return error_response(
                message="Query parameter 'id' is required for deletion.",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        try:
            contact = Contact.objects.get(pk=contact_id)
        except (Contact.DoesNotExist, ValueError):
            return error_response(
                message="Contact message not found.",
                status_code=status.HTTP_404_NOT_FOUND
            )

        contact.delete()
        return success_response(
            message="Contact message deleted successfully.",
            status_code=status.HTTP_200_OK
        )


class EnquiryAPIView(APIView):
    from rest_framework.permissions import AllowAny, IsAdminUser

    def get(self, request, *args, **kwargs):
        enquiry_id = request.query_params.get('id')

        if enquiry_id:
            try:
                enquiry = Enquiry.objects.get(pk=enquiry_id)
            except (Enquiry.DoesNotExist, ValueError):
                return error_response(
                    message="Enquiry not found.",
                    status_code=status.HTTP_404_NOT_FOUND
                )
            serializer = EnquirySerializer(enquiry)
            return success_response(
                data=serializer.data,
                message="Enquiry retrieved successfully."
            )

        enquiries = Enquiry.objects.all()
        enquiries = apply_search_and_filters(
            queryset=enquiries,
            request=request,
            search_fields=['full_name', 'email_address', 'phone_number', 'company_name', 'message'],
            filter_fields={
                'referral': 'how_did_you_hear_about_us',
                'subject': 'subject',
            }
        )
        serializer = EnquirySerializer(enquiries, many=True)
        return success_response(
            data=serializer.data,
            message="Enquiries retrieved successfully."
        )

    def post(self, request, *args, **kwargs):
        serializer = EnquirySerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return success_response(
                data=serializer.data,
                message="Your enquiry has been submitted successfully.",
                status_code=status.HTTP_201_CREATED
            )
        return error_response(
            errors=serializer.errors,
            message="Please correct the errors below.",
            status_code=status.HTTP_400_BAD_REQUEST
        )

    def put(self, request, *args, **kwargs):
        enquiry_id = request.query_params.get('id')

        if not enquiry_id:
            return error_response(
                message="Query parameter 'id' is required for update.",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        try:
            enquiry = Enquiry.objects.get(pk=enquiry_id)
        except (Enquiry.DoesNotExist, ValueError):
            return error_response(
                message="Enquiry not found.",
                status_code=status.HTTP_404_NOT_FOUND
            )

        serializer = EnquirySerializer(enquiry, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return success_response(
                data=serializer.data,
                message="Enquiry updated successfully.",
                status_code=status.HTTP_200_OK
            )
        return error_response(
            errors=serializer.errors,
            message="Please correct the errors below.",
            status_code=status.HTTP_400_BAD_REQUEST
        )

    def delete(self, request, *args, **kwargs):
        enquiry_id = request.query_params.get('id')

        if not enquiry_id:
            return error_response(
                message="Query parameter 'id' is required for deletion.",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        try:
            enquiry = Enquiry.objects.get(pk=enquiry_id)
        except (Enquiry.DoesNotExist, ValueError):
            return error_response(
                message="Enquiry not found.",
                status_code=status.HTTP_404_NOT_FOUND
            )

        enquiry.delete()
        return success_response(
            message="Enquiry deleted successfully.",
            status_code=status.HTTP_200_OK
        )