from django.shortcuts import render
from django.http import HttpRequest

def start_page(request: HttpRequest):
    template = "authenticated" if request.user.is_authenticated else "public"

    return render(request, f"start_page/{template}.html")
