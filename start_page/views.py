from django.shortcuts import render

def start_page(request):
    template = "authenticated" if request.user.is_authenticated else "public"

    return render(request, f"start_page/{template}.html")
