from datetime import date, timedelta, datetime

from asgiref.sync import sync_to_async
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum, F
from django.http import HttpResponse
from django.shortcuts import render
from django.templatetags.tz import timezone
from django.views.decorators.http import require_POST, require_GET
from pydantic import UUID4

from .forms import TrackActivityForm, ProjectForm, CategoryForm
from .models import Category, Activity, Settings, Project


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
async def get_activities(request):
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

  start_date = datetime.strptime(f'{year}-W{week - 1}-1', "%Y-W%W-%w").date()
  weekdays = [start_date + timedelta(days=i) for i in range(7)]

  settings, created = await Settings.objects.aget_or_create(user=request.user)

  return await sync_to_async(render)(
    request,
    'frontend/activities_table.html', {
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
        'HX-Trigger': 'refresh-table',
      },
    )


@login_required
@require_GET
async def get_activity(request, activity_id):
  activity = await Activity.objects.aget(id=activity_id)
  return await sync_to_async(render)(request, 'projects/activity.html', {'activity': activity})


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
      'HX-Trigger': 'refresh-table',
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
      'HX-Trigger': 'refresh-table',
    },
  )


@login_required
@require_GET
async def get_projects(request):
  projects = await sync_to_async(Project.objects.filter)(is_archived=False)
  projects = await sync_to_async(projects.order_by)('customer__number', 'title')

  return await sync_to_async(render)(request, 'projects/project_select.html', {'items': projects})


@login_required
@require_GET
async def get_project(request, project_id):
  project = await Project.objects.aget(id=project_id)
  return await sync_to_async(render)(request, 'projects/project.html', {'project': project})


@login_required
@require_POST
@sync_to_async
def create_project(request):
  form = ProjectForm(request.POST)
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
        'HX-Trigger': 'refresh-table',
      },
    )


@login_required
@require_POST
@sync_to_async
def update_project(request, project_id):
  project = Project.objects.get(id=project_id)
  form = ProjectForm(request.POST, instance=project)
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
      'HX-Trigger': 'refresh-table',
    },
  )


@login_required
@require_POST
async def delete_project(request, project_id):
  project = await Project.objects.aget(id=project_id)
  await project.adelete()

  return HttpResponse(
    status=204,
    headers={
      'HX-Trigger': 'refresh-table',
    },
  )


@login_required
@require_GET
async def get_categories(request, category_id=None):
  selected_category = None
  if category_id:
    selected_category = await Category.objects.aget(id=category_id)

  project_id: UUID4 = request.GET.get('project')
  categories = await sync_to_async(Category.objects.filter)(projects=project_id)

  return await sync_to_async(render)(
    request, 'projects/category_select.html', {'categories': categories, 'selected_category': selected_category})


@login_required
@require_GET
async def get_category(request, category_id):
  category = await Category.objects.aget(id=category_id)
  return await sync_to_async(render)(request, 'projects/category.html', {'category': category})


@login_required
@require_POST
@sync_to_async
def create_category(request):
  form = CategoryForm(request.POST)
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
        'HX-Trigger': 'refresh-table',
      },
    )


@login_required
@require_POST
@sync_to_async
def update_category(request, category_id):
  category = Category.objects.get(id=category_id)
  form = CategoryForm(request.POST, instance=category)
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
      'HX-Trigger': 'refresh-table',
    },
  )


@login_required
@require_POST
async def delete_category(request, category_id):
  category = await Category.objects.aget(id=category_id)
  await category.adelete()

  return HttpResponse(
    status=204,
    headers={
      'HX-Trigger': 'refresh-table',
    },
  )


# Statistics

@login_required
@require_GET
@sync_to_async
def count_activities_per_unit(request, unit: str):
  labels = []
  data = []

  days = request.GET.get('days', 1)
  chart_type = request.GET.get('chart_type', 'pie')

  activities = Activity.objects.filter(
    user=request.user,
    started_at__gte=date.today() - timedelta(days=float(days))
  )

  match unit:
    case 'project':
      target = 'project__title'
    case 'category':
      target = 'category__title'
    case 'customer':
      target = 'project__customer__name'
    case _:
      return HttpResponse(status=400)

  queryset = activities.values(target).annotate(total_duration=Sum(F('ended_at') - F('started_at')))

  queryset = [{'unit': item[target], 'total_duration': item['total_duration']} for item in queryset]

  for item in queryset:
    labels.append(item['unit'])
    data.append(item['total_duration'].total_seconds() / 3600)  # Convert duration to hours

  match chart_type:
    case 'bar':
      template = 'projects/charts/bar_chart.html'
    case 'pie':
      template = 'projects/charts/pie_chart.html'
    case _:
      return HttpResponse(status=400)

  return render(request, template,
                                     {'labels': labels, 'data': data, 'unit': unit})
