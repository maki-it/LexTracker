from asgiref.sync import sync_to_async
from django.contrib.auth import alogout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.shortcuts import render
from django.views.decorators.http import require_GET

from projects.forms import TrackActivityForm
from projects.models import Activity, Project, Settings, Customer

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
  # TODO
  return await sync_to_async(render)(
    request,
    'frontend/reports.html'
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

  paginator = Paginator(customer_list, 25)

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
