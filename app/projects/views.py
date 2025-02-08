from datetime import date

from asgiref.sync import sync_to_async
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.views.generic import View
from django.views.decorators.http import require_POST
from pydantic import UUID4

from .forms import TrackActivityForm
from .models import Category, Activity


@login_required
async def get_categories(request):
  """
  Get all categories
  :param request:
  :return:
  """

  project_id: UUID4 = request.GET.get('project')
  categories = await sync_to_async(Category.objects.filter)(projects=project_id)
  return await sync_to_async(render)(request, 'projects/select_form.html', {'items': categories})

@login_required
async def get_activity(request, activity_id):
  """
  Get a single activity
  :param request:
  :param activity_id:
  :return:
  """

  # TODO: Implement this
  activity = await Activity.objects.aget(id=activity_id)
  pass

@login_required
async def get_activities(request):
  """
  Get all activities
  :param request:
  :return:
  """

  current_week = date.today().isocalendar()[1]
  activities = await sync_to_async(Activity.objects.filter)(
    user=request.user,
    started_at__week=current_week,
  )
  activities = await sync_to_async(activities.order_by)('started_at')

  return await sync_to_async(render)(
    request,
    'projects/activities.html', {
      'activities': activities,
    })


@login_required
@require_POST
@sync_to_async
def save_activity(request):
  form = TrackActivityForm(request.POST)
  form.instance.user = request.user
  try:
    if form.is_valid():
      form.save()
  except Exception as e:
    return render(request, 'frontend/error.html', {'error': str(e)}, status=400)

  if form.errors:
    return render(request, 'frontend/error.html', {'error': form.errors.as_text()}, status=400)
  else:
    return HttpResponse(status=201)

@login_required
@require_POST
async def update_activity(request, activity_id):
  activity = await Activity.objects.aget(id=activity_id)
  # TODO: Implement this


@login_required
@require_POST
async def delete_activity(request, activity_id):
  activity = await Activity.objects.aget(id=activity_id)
  await activity.adelete()

  return HttpResponse(
    status=204,
    # headers={'HX-Refresh': 'true'},
  )
