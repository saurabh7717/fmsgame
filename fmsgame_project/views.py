import urlparse
import urllib2
import urllib
import cgi

from django.contrib.auth.decorators import login_required
from django.shortcuts import render_to_response
from django.http import HttpResponse, Http404, HttpResponseRedirect
from django.core.urlresolvers import reverse
from django.template import RequestContext
from django.views.generic.simple import direct_to_template
from django.views.decorators.cache import cache_control
from django.views.decorators.csrf import csrf_exempt

import fixmystreet
import datetime
import GeoRSS

import settings
from scoreboard import models as scoreboard_models

from BeautifulSoup import BeautifulSoup, NavigableString

states = {'notfound': 'Not Found',
          'fixed': 'Fixed',
          'notfixed': 'Not Fixed',
          }

# The CSRF protection seems to be causing intermittent trouble with this view
# on mobile phones, so I'm turning it off. I don't think the consequences of
# someone forging requests here are all that bad!
@csrf_exempt
@login_required
@cache_control(no_cache=True)
def issue(request, issue_id=None):
    if request.method == 'POST':
        target_url = urlparse.urljoin(settings.FMS_URL, '/report/%s' % issue_id)
        data =  {'submit_update': '1',
                 'id': issue_id,
                 'name': request.user.get_full_name(),
                 'rznvy': openid.ax.type.email,#'fmsgame@gmail.com',  # request.user.email,
                 'email':request.user.email, # check this  
                 #'update': '', # text of the update (e.g., "I put it in the bin")
                 'fixed': '', # checkbox for: Is it fixed?
                 'add_alert': '', # don't add the user to automatic alert notifications
                 'photo': '', 
                }
        state = request.POST.get('state')

        if state == 'fixed':
            data['fixed'] = 1
            data['update'] = 'fmsgame: this is fixed'
            new_points = 1
        elif state == 'notfixed':
            data['update'] = 'fmsgame: this is not fixed'
            new_points = 1
        elif state == 'notfound':
            data['update'] = "fmsgame: this couldn't be found"
            new_points = 1
        else:
            raise Http404

        response = urllib2.urlopen(target_url, urllib.urlencode(data))

        score_obj, created = scoreboard_models.Score.objects.get_or_create(user=request.user)
        old_score = score_obj.score or 0
        score_obj.score = old_score + new_points
        score_obj.save()

        request.session['last_issue_id'] = issue_id
        request.session['last_issue_status'] = state

        # FIXME handle the response   
        return HttpResponseRedirect(reverse('success',args=(issue_id,)))#args=(issue_id,)

    fms_url = 'http://www.fixmystreet.com/report/%s/' %(issue_id)
    fms_response = urllib2.urlopen(fms_url)

    fms_soup = BeautifulSoup(fms_response.read())
    google_maps_link = fms_soup.find('p', {'id': 'sub_map_links' }).a['href']

    split_link = urlparse.urlsplit(google_maps_link)
    useful_string = cgi.parse_qs(split_link.query)['q'][0]
    target_lat, target_long = useful_string.rsplit(None, 1)[1].split('@')[1].split(',')
    issue_summary = fms_soup.find('div', {'id': 'side'}).find('p', {'align': 'right'}).findPrevious('p').string

    extra_context = {
        'target_lat': target_lat, 
        'target_long': target_long,
        'issue_id': issue_id,
        'issue_title': fms_soup.title.string,
        'issue_summary': issue_summary,
        'last_issue_status': states.get(request.session.get('last_issue_status')),
        }

    context = context_instance=RequestContext(request)

    last_issue_id = request.session.get('last_issue_id')

    if issue_id == request.session.get('last_issue_id'):
        template = 'issue_done.html'
    else:
        template = 'issue.html'

    return render_to_response(template, extra_context, context)

@login_required
@cache_control(no_cache=True)
def success(request, template='success.html'):
    try:
        score = request.user.score_set.all()[0].score
    except IndexError:
        # This is because the user doesn't have a score yet. Use zero.
        # This should never happen here.
        score = 0
        
    extra_context = {
        'last_issue_status': states.get(request.session.get('last_issue_status')),
        'score': score,
        }

    context = context_instance=RequestContext(request)
    return render_to_response(template, extra_context, context)

@login_required
@cache_control(no_cache=True)
def found_you(request):
    lat = request.REQUEST.get('lat')
    lon = request.REQUEST.get('lon')

    nearby_issues = fixmystreet.find_nearby_issues(lat=lat, lon=lon)

    # FIXME - sort out hardcoded domain name
    rss_url = "http://fmsgame.mysociety.org/find_issues?lon=%(lon)s&lat=%(lat)s" %dict(lon=lon, lat=lat)
    google_map_url = "http://maps.google.com/maps?q=%s" %urllib.quote(rss_url)

    extra_context = {
        'google_map_url': google_map_url,
        'issue_count': len(nearby_issues),
        }

    context = context_instance=RequestContext(request)
    return render_to_response('located.html', extra_context, context)


  # // Note - we need to display the url for the ser to click on so that the smart
  # // phones offer the user the choice to use the map app rather than the web page.
  #   $("#autolocate_ui")
  #   .html('<a href="'+google_map_url+'">Found you - follow this link, choose "complete action using maps", then using the map walk to a nearby report. Once there tap the pin on the map and follow the link.</a>');

@cache_control(no_cache=True)
def find_issues(request):
    lat = request.REQUEST.get('lat')
    lon = request.REQUEST.get('lon')

    if lat is None or lon is None:
        raise Http404
        
    nearby_issues = fixmystreet.find_nearby_issues(lat=lat, lon=lon)

    rss_items = []
    
    for issue in nearby_issues:
        issue_url = request.build_absolute_uri( '/issue/' + str(issue['id']) )

        description_start = '<h2><a href="' + issue_url + '">Follow me to play</a></h2><br><br>'

        # Not sure why this is not working... should strip out the 'Report on FixMyStreet' link
        # description_end = ''.join(BeautifulSoup( issue['summary'] ).findAll( lambda tag: tag.name != 'a' ))
	list_soup = list(BeautifulSoup(issue['summary']))
	list_soup.pop()
	description_end = str(list_soup)
        #issue_soup = BeautifulSoup(issue['summary'])
        #description_end = ' '.join([x for x in issue_soup.contents if isinstance(x, NavigableString)])

        item = GeoRSS.GeoRSSItem(
            title        = issue['name'],
            link         = issue_url,
            description  = description_start + description_end,
            guid         = GeoRSS.Guid( issue_url ),
            pubDate      = issue['date'],#datetime.datetime.now(),    # FIXME #it's correct
            geo_lat    = str(issue['lat']),
            geo_long   = str(issue['lon']),
        )


        rss_items.append( item )

    rss = GeoRSS.GeoRSS(
        title         = "FixMyStreet Game",
        link          = request.build_absolute_uri(),
        description   = "Foo",
        lastBuildDate = datetime.datetime.now(),
        items         = rss_items,
    )
    
    return HttpResponse(
        content = rss.to_xml(),
        content_type = 'application/rss+xml'
    )

@cache_control(no_cache=True)
def scoreboard(request):
    scores = scoreboard_models.Score.objects.all().order_by('-score')
    context = RequestContext(request)
    if request.user.is_authenticated():
        try:
            user_score = request.user.score_set.all()[0].score
        except IndexError:
            # This is because the user doesn't have a score yet. Use zero.
            user_score = 0
        if user_score > 10: # don't show the 10-cone graphic if it's the only graphic: i.e., 11 or higher
            my_range_of_tens = range(user_score // 10)
            my_range = range(user_score % 10)
        else:
            my_range = range(user_score)
            my_range_of_tens = ()
    else:
        user_score = None
        my_range = ()
        my_range_of_tens = ()

    return render_to_response('scoreboard.html', {'scores': scores, 'score': user_score, 'range_of_tens': my_range_of_tens, 'range': my_range}, context) 

