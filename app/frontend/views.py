from datetime import date, timedelta

from asgiref.sync import sync_to_async
from django.contrib.auth import alogout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.shortcuts import render
from django.views.decorators.http import require_GET

from projects.forms import TrackActivityForm, ProjectForm, CategoryForm
from projects.models import Activity, Project, Settings, Customer, Category
from projects.views import split_activities, duration_sum

from .forms import SettingsForm


@login_required
async def projects(request):
  return await sync_to_async(render)(
    request,
    'frontend/projects.html'
  )


@login_required
async def activities(request):
  form = TrackActivityForm()
  projects = await sync_to_async(Project.objects.filter)(is_archived=False)
  projects = await sync_to_async(projects.order_by)('customer__number', 'title')

  return await sync_to_async(render)(
    request,
    'frontend/activities.html', {
      'form': form,
      'projects': projects,
    })

@login_required
async def activity_form(request, activity_id=None, action=None):
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
      'action': action,
      'activity': activity,
      'settings': settings,
    })

@login_required
async def reports(request):
  types = ['project', 'category', 'customer']

  customers = await sync_to_async(Customer.objects.filter)(is_archived=False)
  customers = await sync_to_async(customers.order_by)('name')

  return await sync_to_async(render)(
    request,
    'frontend/reports.html',
    {
      'types': types,
      'customers': customers,
    },
  )

@login_required
@require_GET
@sync_to_async
def reports_table(request):
  days = request.GET.get('days', 1)
  customer_id = request.GET.get('customer_id', 'all')
  chargeable = request.GET.get('chargeable', 'all')

  activities = Activity.objects.filter(
    user=request.user,
    started_at__gte=date.today() - timedelta(days=float(days)),
  )

  if customer_id != 'all':
    activities = activities.filter(project__customer_id=customer_id)
  else:
    activities = activities.filter(project__customer__is_archived=False)

  if chargeable != 'all':
    activities = activities.filter(is_chargeable=(chargeable=='true'))

  activities = activities.order_by('-started_at')

  split_activities_list, daily_durations = split_activities(activities)
  total_duration = duration_sum(activities)

  start_date = date.today() - timedelta(days=float(days) - 1)
  weekdays = [start_date + timedelta(days=i) for i in range(int(days))]

  settings, created = Settings.objects.get_or_create(user=request.user)

  # Group activities by day
  from collections import defaultdict
  activities_by_day = defaultdict(list)
  for activity in split_activities_list:
    activities_by_day[activity['started_at'].date()].append(activity)

  # Build a list of day entries for pagination
  day_entries = []
  for day in sorted(weekdays, reverse=True):
    day_activities = activities_by_day.get(day, [])
    daily_duration = daily_durations.get(day, timedelta())

    # Only include days with activities, or all days if show_empty_days is enabled
    if settings.show_empty_days or day_activities:
      day_entries.append({
        'date': day,
        'activities': day_activities,
        'duration': daily_duration,
      })

  # Paginate day entries (each day counts as one "row")
  paginator = Paginator(day_entries, settings.table_rows)
  page_number = request.GET.get('page')
  page_obj = paginator.get_page(page_number)

  return render(
    request,
    'frontend/reports_activities_table.html',
    {
      'page_obj': page_obj,
      'total_duration': total_duration,
      'settings': settings,
    },
  )



@login_required
async def customers(request):
  return await sync_to_async(render)(
    request,
    'frontend/customers.html',
  )

@login_required
@require_GET
async def customers_table(request):
  settings = await Settings.objects.aget(user=request.user)
  datetime_format = f"{settings.date_format} {settings.time_format}"

  customer_list = await sync_to_async(Customer.objects.order_by)('number')

  paginator = Paginator(customer_list, settings.table_rows)

  page_number = request.GET.get('page')
  page_obj = await sync_to_async(paginator.get_page)(page_number)

  return await sync_to_async(render)(
    request,
    'frontend/customers_table.html',
    {
      'page_obj': page_obj,
      'datetime_format': datetime_format,
    },
  )

@login_required
async def projects(request):
  if request.path.endswith('categories'):
    view = 'category'
  else:
    view = 'project'

  return await sync_to_async(render)(
    request,
    'frontend/projects.html',
    {
      'view': view,
    },
  )

@login_required
@require_GET
async def projects_table(request):
  settings = await Settings.objects.aget(user=request.user)
  projects_list = await sync_to_async(Project.objects.order_by)('customer__number', 'start_date', 'end_date')

  paginator = Paginator(projects_list, settings.table_rows)

  page_number = request.GET.get('page')
  page_obj = await sync_to_async(paginator.get_page)(page_number)

  return await sync_to_async(render)(
    request,
    'frontend/projects_table.html',
    {
      'page_obj': page_obj,
      'settings': settings,
    },
  )

@login_required
async def project_form(request, project_id=None, action=None):
  form = ProjectForm()
  customers = await sync_to_async(Customer.objects.filter)(is_archived=False)
  customers = await sync_to_async(customers.order_by)('number')

  categories = await sync_to_async(Category.objects.order_by)("title")

  project = None
  if project_id:
    project = await Project.objects.aget(id=project_id)
    form = await sync_to_async(ProjectForm)(instance=project)

  return await sync_to_async(render)(
    request,
    'frontend/project_form.html',
    {
      'form': form,
      'action': action,
      'project': project,
      'customers': customers,
      'categories': categories,
    },
  )

@login_required
@require_GET
async def categories_table(request):
  settings = await Settings.objects.aget(user=request.user)
  categories_list = await sync_to_async(Category.objects.order_by)('title')

  paginator = Paginator(categories_list, settings.table_rows)

  page_number = request.GET.get('page')
  page_obj = await sync_to_async(paginator.get_page)(page_number)

  return await sync_to_async(render)(
    request,
    'frontend/categories_table.html',
    {
      'page_obj': page_obj,
    },
  )

@login_required
async def category_form(request, category_id=None, action=None):
  form = CategoryForm()

  category = None
  if category_id:
    category = await Category.objects.aget(id=category_id)

  return await sync_to_async(render)(
    request,
    'frontend/category_form.html',
    {
      'form': form,
      'action': action,
      'category': category,
    },
  )

async def settings(request):
  settings = await Settings.objects.aget(user=request.user)

  if request.method == 'POST':
    form = SettingsForm(request.POST, instance=settings)
    if await sync_to_async(form.is_valid)():
      await sync_to_async(form.save)()
  else:
    form = SettingsForm(instance=settings)

  return await sync_to_async(render)(
    request,
    'frontend/settings.html',
    {
      'settings': settings,
      'form': form,
    }
  )

@login_required
async def logout(request):
  await alogout(request)
  return await sync_to_async(redirect_to_login)(next='/')
