# -*- coding: utf-8 -*-
import os
import json
import datetime
import time
import sys
import re
import logging
import cgi
from urllib.parse import parse_qs
import requests
import web
from web import form
import forms, mapping, conf, queries , vocabs  , github_sync
import utils as u

web.config.debug = False

# ROUTING

prefix = ''
#prefixLocal = '/musow/'
prefixLocal = prefix
urls = (
	prefix + '/', 'Login',
	prefix + '/logout', 'Logout',
	prefix + '/gitauth', 'Gitauth',
	prefix + '/oauth-callback', 'Oauthcallback',
	prefix + '/welcome-(.+)','Index',
	prefix + '/record-(.+)', 'Record',
	prefix + '/modify-(.+)', 'Modify',
	prefix + '/review-(.+)', 'Review',
	prefix + '/documentation', 'Documentation',
	prefix + '/records', 'Records',
	prefix + '/view-(.+)', 'View',
	prefix + '/term-(.+)', 'Term',
	prefix + '/(sparql)','sparql'
)

app = web.application(urls, globals())

# SESSIONS

store, session, session_data = u.initialize_session(app)


# TEMPLATING

render = web.template.render('templates/', base="layout", cache=False,
								globals={'session':session,'time_now':u.get_timestamp,
								'isinstance':isinstance,'str':str, 'next':next,
								'upper':u.upper, 'get_type':web.form.Checkbox.get_type, 'type':type,
								'Checkbox':web.form.Checkbox})
render2 = web.template.render('templates/', globals={'session':session})

# LOAD FORM, IMPORT VOCABS

with open(conf.myform) as config_form:
	fields = json.load(config_form)

vocabs.import_vocabs(fields)

# ERROR HANDLER

def notfound():
    return web.notfound(render.notfound(user=session['username']))

def internalerror():
    return web.internalerror(render.internalerror(user=session['username']))

class Notfound:
    def GET(self):
        raise web.notfound()

app.notfound = notfound
app.internalerror = internalerror

# UTILS

def key(s):
	fmt = "%Y-%m-%dT%H:%M:%S"
	return datetime.datetime.strptime(s, fmt)


def create_record(data):
	if data and 'action' in data and data.action.startswith('createRecord'):
		record = data.action.split("createRecord",1)[1]
		u.log_output('START NEW RECORD', session['logged_in'], session['username'])
		raise web.seeother(prefixLocal+'record-'+record)
	else:
		u.log_output('ELSE', session['logged_in'], session['username'])
		#raise web.seeother(prefixLocal+'/')

# GITHUB LOGIN
clientId = conf.gitClientID

class Gitauth:
	def GET(self):
		return web.seeother("https://github.com/login/oauth/authorize?client_id="+clientId+"&scope=repo read:user")

class Oauthcallback:
	def GET(self):
		data = web.input()
		code = data.code

		res = github_sync.ask_user_permission(code)

		if res:
			userlogin, usermail = github_sync.get_user_login(res)
			is_valid_user = github_sync.get_github_users(userlogin)
			if is_valid_user == True:
				session['logged_in'] = 'True'
				session['username'] = usermail
				session['ip_address'] = str(web.ctx['ip'])
				# do not store the token
				u.log_output('LOGIN VIA GITHUB', session['logged_in'], session['username'])
				raise web.seeother(prefixLocal+'welcome-1')

		else:
			print("bad request to github oauth")
			return internalerror()

# CLASSIC LOGIN : TO BE REMOVED

class Login:
	def GET(self):
		if session.username != 'anonymous':
			u.log_output('HOMEPAGE LOGGED IN', session['logged_in'], session['username'])
			raise web.seeother(prefixLocal+'welcome-1')
		else:
			u.log_output('HOMEPAGE ANONYMOUS', session['logged_in'], session['username'])
			return render.login(user='anonymous')

	def POST(self):
		data = web.input()
		create_record(data)


class Logout:
	def GET(self):
		u.log_output('LOGOUT', session['logged_in'], session['username'])
		session['logged_in'] = 'False'
		session['username'] = 'anonymous'
		session['ip_address'] = str(web.ctx['ip'])
		raise web.seeother(prefixLocal+'/')

	def POST(self):
		data = web.input()
		create_record(data)

# BACKEND Index: show list or records (only logged users)

class Index:
	def GET(self, page):
		web.header("Content-Type","text/html; charset=utf-8")
		web.header('Access-Control-Allow-Origin', '*')
		web.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
		session['ip_address'] = str(web.ctx['ip'])
		filterRecords = ''
		if session.username != 'anonymous':
			session['logged_in'] = 'True'
			userID = session['username'].replace('@','-at-').replace('.','-dot-')
			alll = queries.countAll()
			all, notreviewed, underreview, published = queries.getCountings()
			results = queries.getRecordsPagination(page)
			records = reversed(sorted(results, key=lambda tup: key(tup[4][:-5]) ))
			u.log_output('WELCOME PAGE', session['logged_in'], session['username'])

			return render.index(wikilist=records, user=session['username'],
				varIDpage=str(time.time()).replace('.','-'), alll=alll, all=all,
				notreviewed=notreviewed,underreview=underreview,
				published=published, page=page,pagination=conf.pagination,
				filter=filterRecords, filterName = 'filterAll')
		else:
			session['logged_in'] = 'False'
			u.log_output('WELCOME PAGE NOT LOGGED IN', session['logged_in'], session['username'])
			raise web.seeother(prefixLocal+'/')

	def POST(self, page):
		actions = web.input()
		web.header("Content-Type","text/html; charset=utf-8")
		web.header('Access-Control-Allow-Origin', '*')
		web.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
		session['ip_address'] = str(web.ctx['ip'])

		filter_values = {
			"filterNew": "?g base:publicationStage ?anyValue . FILTER (isLiteral(?anyValue) && lcase(str(?anyValue)) = 'not modified') .",
			"filterReviewed": "?g base:publicationStage ?anyValue . FILTER (isLiteral(?anyValue) && lcase(str(?anyValue)) = 'modified') .",
			"filterPublished": "?g base:publicationStage ?anyValue . FILTER (isLiteral(?anyValue) && lcase(str(?anyValue)) = 'published') .",
			"filterAll": "none"
		}

		# filter records
		if actions.action.startswith('filter'):
			filterRecords = filter_values[actions.action]
			filterRecords = filterRecords if filterRecords not in ['none',None] else ''
			filterName = actions.action
			page = 1
			results = queries.getRecordsPagination(page, filterRecords)
			records = reversed(sorted(results, key=lambda tup: key(tup[4][:-5]) ))
			alll = queries.countAll()
			all, notreviewed, underreview, published = queries.getCountings(filterRecords)
			filterRecords = filterRecords if filterRecords != '' else 'none'

			return render.index(wikilist=records, user=session['username'],
				varIDpage=str(time.time()).replace('.','-'),
				alll=alll, all=all, notreviewed=notreviewed,
				underreview=underreview, published=published,
				page=page, pagination=conf.pagination,
				filter= filterRecords, filterName = filterName)

		# create a new record (logged users)
		elif actions.action.startswith('createRecord'):
			record = actions.action.split("createRecord",1)[1]
			u.log_output('START NEW RECORD (LOGGED IN)', session['logged_in'], session['username'], record )
			raise web.seeother(prefixLocal+'record-'+record)

		# delete a record (but not the dump in /records folder)
		elif actions.action.startswith('deleteRecord'):
			graph = actions.action.split("deleteRecord",1)[1].split(' __')[0]
			filterRecords = actions.action.split('deleteRecord',1)[1].split(' __')[1]
			queries.deleteRecord(graph)
			userID = session['username'].replace('@','-at-').replace('.','-dot-')
			if conf.github_backup == True: # path hardcoded, to be improved
				file_path = "records/"+graph.split(conf.base)[1].rsplit('/',1)[0]+".ttl"
				github_sync.delete_file(file_path,"main")
			u.log_output('DELETE RECORD', session['logged_in'], session['username'], graph )
			if filterRecords in ['none',None]:
				raise web.seeother(prefixLocal+'welcome-'+page)
			else:
				filterName = [k if v == filterRecords else 'filterName' for k,v in filter_values.items()][0]
				results = queries.getRecordsPagination(page,filterRecords)
				records = reversed(sorted(results, key=lambda tup: key(tup[4][:-5]) ))
				alll = queries.countAll()
				all, notreviewed, underreview, published = queries.getCountings(filterRecords)

				return render.index(wikilist=records, user=session['username'],
					varIDpage=str(time.time()).replace('.','-'),
					alll=alll, all=all, notreviewed=notreviewed,
					underreview=underreview, published=published,
					page=page, pagination=conf.pagination,
					filter= filterRecords, filterName = filterName)

		# modify a record
		elif actions.action.startswith('modify'):
			record = actions.action.split(conf.name,1)[1].replace('/','')
			u.log_output('MODIFY RECORD', session['logged_in'], session['username'], record )
			raise web.seeother(prefixLocal+'modify-'+record)

		# start review of a record
		elif actions.action.startswith('review'):
			record = actions.action.split(conf.name,1)[1].replace('/','')
			u.log_output('REVIEW RECORD', session['logged_in'], session['username'], record )
			raise web.seeother(prefixLocal+'review-'+record)

		# change page
		elif actions.action.startswith('changepage'):
			pag = actions.action.split('changepage-',1)[1].split(' __')[0]
			filterRecords = actions.action.split('changepage-',1)[1].split(' __')[1]
			if filterRecords in ['none',None]:
				raise web.seeother(prefixLocal+'welcome-'+pag)
			else:
				filterName = [k if v == filterRecords else '' for k,v in filter_values.items()][0]
				results = queries.getRecordsPagination(pag, filterRecords)
				records = reversed(sorted(results, key=lambda tup: key(tup[4][:-5]) ))
				alll = queries.countAll()
				all, notreviewed, underreview, published = queries.getCountings(filterRecords)

				return render.index( wikilist=records, user=session['username'],
					varIDpage=str(time.time()).replace('.','-'),
					alll=alll, all=all, notreviewed=notreviewed,
					underreview=underreview, published=published,
					page=page, pagination=conf.pagination,
					filter= filterRecords, filterName = filterName)

		# login or create a new record
		else:
			create_record(data)

# FORM: create a new record (both logged in and anonymous users)

class Record(object):
	def GET(self, name):
		web.header("Cache-Control", "no-cache, max-age=0, must-revalidate, no-store")
		web.header("Content-Type","text/html; charset=utf-8")
		web.header('Access-Control-Allow-Origin', '*')
		web.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')

		session['ip_address'] = str(web.ctx['ip'])
		user = session['username']
		logged_in = True if user != 'anonymous' else False
		u.log_output('GET RECORD FORM', session['logged_in'], session['username'])
		block_user, limit = u.check_ip(str(web.ctx['ip']), str(datetime.datetime.now()) )
		f = forms.get_form(conf.myform)
		return render.record(record_form=f, pageID=name, user=user, alert=block_user, limit=limit)

	def POST(self, name):
		web.header("Content-Type","text/html; charset=utf-8")
		web.header('Access-Control-Allow-Origin', '*')
		web.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
		f = forms.get_form(conf.myform)
		user = session['username']
		session['ip_address'] = str(web.ctx['ip'])
		u.write_ip(str(datetime.datetime.now()), str(web.ctx['ip']), 'POST')

		if not f.validates():
			u.log_output('SUBMIT INVALID FORM', session['logged_in'], session['username'],recordID)
			return render.record(record_form=f, pageID=name, user=user)
		else:
			recordData = web.input()
			print(recordData)
			if 'action' in recordData:
				create_record(recordData)
			recordID = recordData.recordID if 'recordID' in recordData else None
			u.log_output('CREATED RECORD', session['logged_in'], session['username'],recordID)
			if recordID:
				userID = user.replace('@','-at-').replace('.','-dot-')
				file_path = mapping.inputToRDF(recordData, userID, 'not modified')
				if conf.github_backup == True:
					github_sync.push(file_path,"main")
				whereto = prefixLocal+'/' if user == 'anonymous' else prefixLocal+'welcome-1'
				raise web.seeother(whereto)
			else:
				create_record(data)

# FORM: modify a  record (only logged in users)

class Modify(object):
	def GET(self, name):
		web.header("Cache-Control", "no-cache, max-age=0, must-revalidate, no-store")
		web.header("Content-Type","text/html; charset=utf-8")
		web.header('Access-Control-Allow-Origin', '*')
		web.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
		session['ip_address'] = str(web.ctx['ip'])
		if session['username'] != 'anonymous':
			session_data['logged_in'] = 'True'
			graphToRebuild = conf.base+name+'/'
			recordID = name
			data = queries.getData(graphToRebuild)
			u.log_output('START MODIFY RECORD', session['logged_in'], session['username'], recordID )
			f = forms.get_form(conf.myform)
			ids_dropdown = u.get_dropdowns(fields)
			return render.modify(graphdata=data, pageID=recordID, record_form=f,
							user=session['username'],ids_dropdown=ids_dropdown)
		else:
			session['logged_in'] = 'False'
			raise web.seeother(prefixLocal+'/')

	# TODO validate form!
	def POST(self, name):
		web.header("Content-Type","text/html; charset=utf-8")
		web.header('Access-Control-Allow-Origin', '*')
		web.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
		recordData = web.input()
		session['ip_address'] = str(web.ctx['ip'])

		if 'action' in recordData:
			create_record(recordData)
		else:
			recordID = recordData.recordID
			userID = session['username'].replace('@','-at-').replace('.','-dot-')
			graphToClear = conf.base+name+'/'
			file_path = mapping.inputToRDF(recordData, userID, 'modified', graphToClear)
			if conf.github_backup == True:
				github_sync.push(file_path,"main")
			u.log_output('MODIFIED RECORD', session['logged_in'], session['username'], recordID )
			raise web.seeother(prefixLocal+'welcome-1')

# FORM: review a record for publication (only logged in users)

class Review(object):
	def GET(self, name):
		web.header("Cache-Control", "no-cache, max-age=0, must-revalidate, no-store")
		web.header("Content-Type","text/html; charset=utf-8")
		web.header('Access-Control-Allow-Origin', '*')
		web.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
		graphToRebuild = conf.base+name+'/'
		recordID = name
		data = queries.getData(graphToRebuild)
		session['ip_address'] = str(web.ctx['ip'])
		u.log_output('START REVIEW RECORD', session['logged_in'], session['username'], recordID )
		f = forms.get_form(conf.myform)
		ids_dropdown = u.get_dropdowns(fields)
		return render.review(graphdata=data, pageID=recordID, record_form=f,
							graph=graphToRebuild, user=session['username'],
							ids_dropdown=ids_dropdown)


	def POST(self, name):
		web.header("Content-Type","text/html; charset=utf-8")
		web.header('Access-Control-Allow-Origin', '*')
		web.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
		actions = web.input()
		session['ip_address'] = str(web.ctx['ip'])

		# save the new record for future publication
		if actions.action.startswith('save'):
			recordData = web.input()
			recordID = recordData.recordID
			userID = session['username'].replace('@','-at-').replace('.','-dot-')
			graphToClear = conf.base+name+'/'
			file_path = mapping.inputToRDF(recordData, userID, 'modified',graphToClear)
			if conf.github_backup == True:
				github_sync.push(file_path,"main")
			u.log_output('REVIEWED (NOT PUBLISHED) RECORD', session['logged_in'], session['username'], recordID )
			raise web.seeother(prefixLocal+'welcome-1')

		# publish
		elif actions.action.startswith('publish'):
			recordData = web.input()
			userID = session['username'].replace('@','-at-').replace('.','-dot-')
			graphToClear = conf.base+name+'/'
			file_path= mapping.inputToRDF(recordData, userID, 'published',graphToClear)
			if conf.github_backup == True:
				github_sync.push(file_path,"main")
			u.log_output('PUBLISHED RECORD', session['logged_in'], session['username'], name )
			raise web.seeother(prefixLocal+'welcome-1')

		# login or create new record
		else:
			create_record(actions)
# FORM: view documentation

class Documentation:
	def GET(self):
		return render.documentation(user=session['username'])

	def POST(self):
		actions = web.input()
		create_record(actions)

# VIEW : lists of types of records of the catalogue

class Records:
	def GET(self):
		records = queries.getRecords()
		alll = queries.countAll()
		filtersBrowse = queries.getBrowsingFilters()
		return render.records(user=session['username'], data=records,
							title='Latest added resources', r_base=conf.base,
							alll=alll, filters=filtersBrowse)

	def POST(self):
		actions = web.input()
		create_record(actions)

# VIEW : single record

class View(object):
	def GET(self, name):
		base = conf.base
		record = base+name
		data = dict(queries.getData(record+'/'))
		stage = data['stage'][0]
		title = [data[k][0] for k,v in data.items() \
				for field in fields if (field['disambiguate'] == "True" \
				and k == field['id'])][0]
		data_labels = { field['label']:v for k,v in data.items() \
						for field in fields if k == field['id']}

		return render.view(user=session['username'], graphdata=data_labels,
						graphID=name, title=title, stage=stage, base=base)

	def POST(self,name):
		data = web.input()
		create_record(data)

# TERM : vocabulary terms and newly created entities

class Term(object):
	def GET(self, name):
		data = queries.describeTerm(name)
		print(data)
		count = len([ result["subject"]["value"] \
					for result in data["results"]["bindings"] \
					if (name in result["object"]["value"] and result["object"]["type"] == 'uri') ])

		return render.term(user=session['username'], data=data, count=count)

# QUERY: endpoint GUI

class sparql:
    def GET(self, active):
        content_type = web.ctx.env.get('CONTENT_TYPE')
        return self.__run_query_string(active, web.ctx.env.get("QUERY_STRING"), content_type)

    def POST(self, active):
        content_type = web.ctx.env.get('CONTENT_TYPE')
        web.debug("The content_type value: ")
        web.debug(content_type)

        cur_data = web.data()
        if "application/x-www-form-urlencoded" in content_type:
            print ("QUERY TO ENDPOINT:", cur_data)
            return self.__run_query_string(active, cur_data, True, content_type)
        elif "application/sparql-query" in content_type:
            print("QUERY TO ENDPOINT:", cur_data)
            return self.__contact_tp(cur_data, True, content_type)
        else:
            raise web.redirect("/sparql")

    def __contact_tp(self, data, is_post, content_type):
        accept = web.ctx.env.get('HTTP_ACCEPT')
        if accept is None or accept == "*/*" or accept == "":
            accept = "application/sparql-results+xml"
        if is_post: # CHANGE
            req = requests.post(conf.myPublicEndpoint, data=data,
                                headers={'content-type': content_type, "accept": accept})
        else: # CHANGE
            req = requests.get("%s?%s" % (conf.myPublicEndpoint, data),
                               headers={'content-type': content_type, "accept": accept})

        if req.status_code == 200:
            web.header('Access-Control-Allow-Origin', '*')
            web.header('Access-Control-Allow-Credentials', 'true')
            web.header('Content-Type', req.headers["content-type"])

            return req.text
        else:
            raise web.HTTPError(
                str(req.status_code), {"Content-Type": req.headers["content-type"]}, req.text)

    def __run_query_string(self, active, query_string, is_post=False,
                           content_type="application/x-www-form-urlencoded"):
        parsed_query = parse_qs(query_string)
        if query_string is None or query_string.strip() == "":
            return render.sparql(active, user='anonymous')
        if re.search("updates?", query_string, re.IGNORECASE) is None:
            if "query" in parsed_query:
                return self.__contact_tp(query_string, is_post, content_type)
            else:
                raise web.redirect(conf.myPublicEndpoint)
        else:
            raise web.HTTPError(
                "403", {"Content-Type": "text/plain"}, "SPARQL Update queries are not permitted.")


if __name__ == "__main__":
	app.run()
