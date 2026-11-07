from django.shortcuts import render, HttpResponse

# Create your views here.
def home(request):
    return HttpResponse("Hello, world. You're at the tickSightings home page.")
    #return render(request, 'home.html')

