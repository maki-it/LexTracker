from datetime import date, timedelta, datetime

from asgiref.sync import sync_to_async
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.templatetags.tz import timezone
from django.urls import reverse
from django.views.decorators.http import require_POST
from pydantic import UUID4

from .forms import TrackActivityForm
from .models import Category, Activity, Settings


def split_activities(activities):
  split_activities = []
  daily_durations = {}
  for activity in activities:
    start = activity.started_at
    end = activity.ended_at
    while start.date() < end.date():
      next_day = datetime.combine(
        start.date(),
        datetime.max.time(),
        tzinfo=timezone.get_current_timezone()
      )
      split_activities.append({
        'id': activity.id,
        'started_at': start,
        'ended_at': next_day,
        'project': activity.project,
        'category': activity.category,
        'is_chargeable': activity.is_chargeable,
        'notes': activity.notes,
      })
      daily_durations[start.date()] = daily_durations.get(start.date(), timedelta()) + (next_day - start)
      start = next_day + timedelta(seconds=1)
    split_activities.append({
      'id': activity.id,
      'started_at': start,
      'ended_at': end,
      'project': activity.project,
      'category': activity.category,
      'is_chargeable': activity.is_chargeable,
      'notes': activity.notes,
    })
    daily_durations[start.date()] = daily_durations.get(start.date(), timedelta()) + (end - start)
  return sorted(split_activities, key=lambda x: x['started_at'], reverse=True), daily_durations

def duration_sum(activities):
  total_duration = timedelta()
  for activity in activities:
    total_duration += activity.ended_at - activity.started_at
  return total_duration

@login_required
async def get_categories(request, category_id=None):
  """
  Get all categories
  :param category_id:
  :param request:
  :return:
  """

  selected_category = None
  if category_id:
    selected_category = await Category.objects.aget(id=category_id)

  project_id: UUID4 = request.GET.get('project')
  categories = await sync_to_async(Category.objects.filter)(projects=project_id)

  return await sync_to_async(render)(
    request, 'projects/category_select.html', {'items': categories, 'selected_category': selected_category})

@login_required
async def get_activities(request):
  """
  Get all activities
  :param request:
  :param d: first day of the week to get activities for
  :return:
  """

  today = date.today()
  current_year_week = f"{today.year}-W{today.isocalendar()[1]:02}"
  d = request.GET.get('week') or current_year_week
  year = int(d.split('-')[0])
  week = int(d.split('-W')[1])

  activities = await sync_to_async(Activity.objects.filter)(
    user=request.user,
    started_at__year=year,
    started_at__week=week,
  )
  activities = await sync_to_async(activities.order_by)('-started_at')
  split_activities_list, daily_durations = await sync_to_async(split_activities)(activities)
  total_duration = await sync_to_async(duration_sum)(activities)

  start_date = datetime.strptime(f'{year}-W{week-1}-1', "%Y-W%W-%w").date()
  weekdays = [start_date + timedelta(days=i) for i in range(7)]

  settings, created = await Settings.objects.aget_or_create(user=request.user)

  return await sync_to_async(render)(
    request,
    'projects/activities.html', {
      'activities': split_activities_list,
      'total_duration': total_duration,
      'week_input_val': d,
      'week_input_max': current_year_week,
      'daily_durations': daily_durations,
      'weekdays': sorted(weekdays, reverse=True),
      'settings': settings,
    })


@login_required
@require_POST
@sync_to_async
def create_activity(request):
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
    return HttpResponse(
      status=204,
      headers={
          'HX-Trigger': 'activities-updated',
      },
    )

@login_required
@require_POST
@sync_to_async
def update_activity(request, activity_id):
  activity = Activity.objects.get(id=activity_id)
  form = TrackActivityForm(request.POST, instance=activity)
  try:
    if form.is_valid():
      form.save()
    else:
      return render(request, 'frontend/error.html', {'error': form.errors.as_text()}, status=400)
  except Exception as e:
    return render(request, 'frontend/error.html', {'error': str(e)}, status=400)

  return HttpResponse(
    status=204,
    headers={
      'HX-Trigger': 'activities-updated',
    },
  )


@login_required
@require_POST
async def delete_activity(request, activity_id):
  activity = await Activity.objects.aget(id=activity_id)
  await activity.adelete()

  return HttpResponse(
    status=204,
    headers={
      'HX-Trigger': 'activities-updated',
    },
  )
