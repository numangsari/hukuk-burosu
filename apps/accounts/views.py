from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.views import View

from .forms import PinChangeForm, PinLoginForm
from .models import User


class PinLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = PinLoginForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["users"] = User.objects.filter(is_active=True)
        return ctx


class PinChangeView(View):
    template_name = "accounts/pin_change.html"

    def get(self, request):
        return render(request, self.template_name, {"form": PinChangeForm(request.user)})

    def post(self, request):
        form = PinChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "PIN değiştirildi.")
            return redirect("core:home")
        return render(request, self.template_name, {"form": form})
