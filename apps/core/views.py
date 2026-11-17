from django.shortcuts import render
from rest_framework.views import APIView
from utils.responses import success_response,error_response
from rest_framework import status
class HealthApiView(APIView):
    def get(self,request):
        return success_response(message="Everything works!!!",status_code=status.HTTP_200_OK)