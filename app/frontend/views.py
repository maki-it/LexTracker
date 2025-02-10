from datetime import date

from asgiref.sync import sync_to_async
from django.contrib.auth import alogout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import render

from projects.forms import TrackActivityForm
from projects.models import Activity, Project, Settings


@login_required
async def history(request):
  return render(request, 'frontend/history.html')


@login_required
async def time_tracker(request):
  form = TrackActivityForm()
  projects = await sync_to_async(Project.objects.filter)(is_archived=False)
  projects = await sync_to_async(projects.order_by)('customer__number', 'title')

  return await sync_to_async(render)(
    request,
    'frontend/time_tracker.html', {
      'form': form,
      'projects': projects,
    })

@login_required
async def activity_form(request, activity_id=None):
  form = TrackActivityForm()
  projects = await sync_to_async(Project.objects.filter)(is_archived=False)
  projects = await sync_to_async(projects.order_by)('customer__number', 'title')

  activity = None
  if activity_id:
    activity = await Activity.objects.aget(id=activity_id)
    form = TrackActivityForm(instance=activity)

  settings, created = await Settings.objects.aget_or_create(user=request.user)

  return await sync_to_async(render)(
    request,
    'frontend/activity_form.html', {
      'form': form,
      'projects': projects,
      'activity': activity,
      'settings': settings,
    })

@login_required
async def reports(request):
  # TODO Make paginated view
  return render(request, 'frontend/reports.html')

@login_required
async def logout(request):
  await alogout(request)
  return await sync_to_async(redirect_to_login)(next='/')
