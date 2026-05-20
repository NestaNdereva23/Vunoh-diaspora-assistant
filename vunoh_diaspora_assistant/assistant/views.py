from django.shortcuts import render
from django.views import View
from .models import Task
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
import logging
import json
from .services import process_task

logger = logging.getLogger(__name__)

def task_to_dict(task: Task) -> dict:
    return{
       "id": str(task.id),
        "task_code": task.task_code,
        "intent": task.intent,
        "entities": task.entities,
        "risk_score": task.risk_score,
        "status": task.status,
        "assigned_team": task.assigned_team,
        "created_at": task.created_at.isoformat(),
        "steps": [
            {
                "step_order": s.step_order,
                "description": s.description,
                "is_complete": s.is_complete,
            }
            for s in task.steps.all()
        ],
        "messages": {
            m.channel: m.body
            for m in task.messages.all()
        },  
    }

class DashboardView(View):
    def get(self, request):
        tasks = Task.objects.prefetch_related(
            "steps", "messages", "status_history"
        ).all()

        return render(request, "assistant/dashboard.html", {"tasks": tasks})
    

class TaskDetailView(View):
    """Get /tasks/<uuid:pk>/ return full task json"""

    def get(self, request, pk):
        try:
            task = Task.objects.prefetch_related("steps", "messages", "status_history").get(pk=pk)
        except Task.DoesNotExist:
            return JsonResponse({"error": "Task not found."}, status=404)

        return JsonResponse(task_to_dict(task))

@method_decorator(csrf_exempt, name="dispatch")
class TaskSubmitView(View):
    """
    POST /tasks/submit/
    Body: { "message": "I need to send KES 15,000 to my mother in Kisumu urgently." }
    Returns: 201 with full task JSON on success, 400/500 on error.
 
    csrf_exempt here because the frontend sends JSON via fetch.
    In production, pass the CSRF token in the request header instead.
    """
 
    def post(self, request):
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON body."}, status=400)
 
        message = body.get("message", "").strip()
        if not message:
            return JsonResponse({"error": "The 'message' field is required."}, status=400)
 
        if len(message) > 1000:
            return JsonResponse({"error": "Message is too long. Max 1000 characters."}, status=400)
 
        try:
            task = process_task(message)
        except RuntimeError as e:
            # Expected errors — bad AI response, API key missing, etc.
            logger.error("process_task failed: %s", e)
            return JsonResponse({"error": str(e)}, status=502)
        except Exception as e:
            # Unexpected errors — log fully, return generic message
            logger.exception("Unexpected error in process_task: %s", e)
            return JsonResponse(
                {"error": "An unexpected error occurred. Please try again."},
                status=500,
            )
 
        return JsonResponse(task_to_dict(task), status=201)
