# my_app/urls.py

# api/urls.py

from django.urls import path
from .views import register, login, analyze_resume, analyze_created_resume, chat, strengthen_content

urlpatterns = [
    path('register/', register),
    path('login/', login),
    path('analyze-resume/', analyze_resume),
    path('analyze_created_resume/', analyze_created_resume),
    path('chat/', chat),
    path('strengthen_content/',strengthen_content),
    
      
]
