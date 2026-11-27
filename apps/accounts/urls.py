from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import *
urlpatterns = [
    
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("roles/", RoleView.as_view(), name="roles"),
    path("users/", UserView.as_view(), name="users"),
    path("addresses/", UserAddressView.as_view(), name="user-addresses"),
    path("send-otp/", SendOTPView.as_view(), name="send-otp"),
    path("verify-otp/", VerifyOTPView.as_view(), name="verify-otp"),
    path("permissions/", UserPermissionsAPIView.as_view(), name="user-permissions"),
    path("role-permissions/", RoleModulePermissionAPIView.as_view(), name="role-module-permissions"),
    path("modules/", ModuleAPIView.as_view(), name="modules"),
    path("forgot-password/", ForgotPasswordAPIView.as_view(), name="forgot-password"),
    path("reset-password/", ResetPasswordAPIView.as_view(), name="reset-password"),

]
