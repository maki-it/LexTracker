from datetime import date

from asgiref.sync import sync_to_async
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .forms import TrackActivityForm
from projects.models import Activity, Project
from lexoffice.models import Customer


@login_required
async def index(request):
  return render(request, 'frontend/index.html')


@login_required
async def time_tracker(request):

  form = TrackActivityForm(request.POST or None)

  if request.POST:
    if await sync_to_async(form.is_valid)():
      form.instance.user = request.user
      await sync_to_async(form.save)(commit=True)

  projects = await sync_to_async(Project.objects.filter)(is_archived=False)
  projects = await sync_to_async(projects.order_by)('customer__number', 'title')

  return await sync_to_async(render)(
    request,
    'frontend/time_tracker.html', {
      'form': form,
      'projects': projects,
    })

async def activities(request):
  current_week = date.today().isocalendar()[1]
  activities = await sync_to_async(Activity.objects.filter)(
    user=request.user,
    started_at__week=current_week,
  )

  return await sync_to_async(render)(
    request,
    'frontend/activities.html', {
      'activities': activities,
    })

@login_required
async def reports(request):
  # TODO Make paginated view
  return render(request, 'frontend/reports.html')


@login_required
async def settings(request):
  return render(request, 'frontend/settings.html')
