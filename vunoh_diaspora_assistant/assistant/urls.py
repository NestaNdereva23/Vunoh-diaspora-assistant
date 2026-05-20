from django.urls import path
from . import views

app_name = "assistant"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("tasks/submit/", views.TaskSubmitView.as_view(), name="task_submit"),
 
    # Task detail (GET — returns task + steps + messages as JSON)
    path("tasks/<uuid:pk>/", views.TaskDetailView.as_view(), name="task_detail"),
    
]